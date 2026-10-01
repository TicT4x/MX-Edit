#!/bin/sh
# MX5 Bridge @VERSION@ (inoffiziell) - Datenbankdienst
#
# Beantwortet Anfragen der Bridge-QML aus der Rig-Datenbank des Geraets.
# Austausch ueber Dateien in /tmp/mx5bridge (Name = Art + laufende Nummer):
#   q<N>.sql   Lese-Anfrage (Befehl 0x08): SQL-Text, nur lesend (sqlite3 -safe: kein
#              .system/.shell, kein readfile/writefile; fsdir liest weiter Verzeichnisse)
#   w<N>.sql   Schreib-Anfrage (Befehl 0x09): SQL-Anweisungen, laufen als eine
#              Transaktion (begin immediate ... commit); beim ersten Fehler wird
#              abgebrochen und nichts geschrieben. Vor dem ersten Schreiben nach
#              dem Start wird die Datenbank gesichert (Online-Backup).
#   a<N>.sql   Aktion (Befehl 0x0A): status | backup | restore | restart | diag |
#              nam-on | nam-off (NAM-Mod umschalten + App-Neustart)
#   s<N>.sql   Shell (Befehl 0x0B): Shell-Skript als root, Antwort [{rc, out}] (stdout und
#              stderr); darueber laufen die Dateizugriffe des PCs
#   *.go       Marker: Anfrage vollstaendig geschrieben
#   *.r/       Antwort: Verzeichnis, dessen Dateinamen sie tragen - JSON {ok, rows, err},
#              base64url in Stuecken zu 240 Zeichen, Name <Nummer ab 10000>_<Stueck>;
#              die QML liest es mit App.entryList. (Bis 0.5 eine JS-Datei, die die QML
#              importierte - jeder Import liess den Speicher der App um ~2,5 KB wachsen.)
#   *.rdy      Marker: Antwort vollstaendig
#   *.done     Marker: Antwort gelesen -> alles zu N wird geloescht
#
# Warten: read -t auf einer eigenen FIFO (kein Prozessstart je Durchlauf), 40 ms solange
# Anfragen kommen, nach 5 s Ruhe 100 ms. Zeitlimits: BusyBox hat kein 'timeout', run_tmo
# beendet einen Befehl nach der Frist (Waechter-Subshell, die ebenfalls per read -t wartet).
#
# Sicherung: $BAK (Online-Backup mit sqlite3 .backup, auch bei laufender App
# konsistent). $WRITTEN markiert, dass seit der Sicherung geschrieben wurde.
# Wiederherstellung laeuft ueber die Startschleife (/usr/Evil/Scripts/evil):
#   prestart   vor jedem App-Start: Sicherung zurueckspielen, wenn $RESTORE
#              angefordert wurde oder die App dreimal kurz nach dem Start
#              abgestuerzt ist und seit der Sicherung geschrieben wurde
#   postexit   nach jedem App-Ende: Absturzzaehler pflegen
#
# NAM-Mod (optional, github.com/lolgab/headrush-nam-mod; nur wenn die Firmware mit ihr gebaut
# wurde): Die Startschleife startet die App nur dann mit NAM (LD_PRELOAD), wenn
# 'mx5bridge-db.sh nam' ja sagt - NAM ist eingeschaltet, solange $NAM_OFF fehlt. Aktionen
# nam-on/nam-off schalten um und starten die App neu. Stuerzt die App mit NAM dreimal in
# Folge kurz nach dem Start ab, schaltet postexit NAM ab ($NAM_OFF mit Inhalt 'auto'),
# bevor eine Datenbank-Wiederherstellung in Frage kommt.
#
# Aufruf: mx5bridge-db.sh daemon        (gestartet von runevil)
#         mx5bridge-db.sh prestart      (aus /usr/Evil/Scripts/evil)
#         mx5bridge-db.sh nam           (aus evil: Exit-Code 0 = mit NAM starten)
#         mx5bridge-db.sh postexit <exitcode> <startzeit>

EVIL=/media/az01-internal/Evil
DB=$EVIL/evil.db
DIR=/tmp/mx5bridge
SQLITE=/usr/Evil/Scripts/mx5bridge-sqlite3
DIAG=/usr/Evil/Scripts/mx5bridge-diag.sh
LOCK=/tmp/mx5bridge.db.lock
STATE=$EVIL/mx5bridge          # ueberlebt Werksreset (der loescht nur Resources und usb_mnt)
BAK=$STATE/evil.db.mx5bak
BAD=$STATE/evil.db.mx5bad      # Datenbank, die durch eine Wiederherstellung ersetzt wurde
WRITTEN=$STATE/written         # seit der Sicherung wurde geschrieben
RESTORE=$STATE/restore         # Wiederherstellung beim naechsten App-Start angefordert
RESTART=$DIR/restart           # App-Neustart durch die Bridge (kein Ausschalten)
CRASHES=$DIR/crashes           # Zaehler kurzer Abstuerze in Folge
TICK=$DIR/tick.fifo            # Warten ohne Prozessstart (read -t), niemand schreibt hinein
NAM_LIB=/usr/Evil/libnam_preload.so     # nur in Firmware mit NAM-Mod
NAM_INFO=/usr/Evil/Scripts/mx5bridge-nam.txt  # Herkunft der Mod (build.py)
NAM_OFF=$STATE/nam-aus         # NAM abgeschaltet (Inhalt 'auto' = vom Absturzwaechter)
NAM_ACTIVE=$DIR/nam-aktiv      # die laufende App wurde mit NAM gestartet
CRASH_SECS=90                  # App-Ende innerhalb dieser Zeit nach dem Start = Absturz
CRASH_MAX=3
T_READ=20                      # Zeitlimits in Sekunden
T_WRITE=30
T_SHELL=60
T_BACKUP=60

log() { logger -t mx5bridge-db -- "$*"; }

# Befehl mit Zeitlimit: run_tmo <sek> <eingabe> <ausgabe> <fehler> befehl...
# Liefert den Exit-Code des Befehls, 137 nach Ablauf der Frist (dann steht das in <fehler>).
run_tmo() {
	secs=$1 in=$2 out=$3 err=$4
	shift 4
	"$@" < "$in" > "$out" 2> "$err" &
	pid=$!
	( read -t "$secs" x <&7; kill -9 $pid 2>/dev/null ) &
	wd=$!
	wait $pid
	rc=$?
	kill $wd 2>/dev/null
	wait $wd 2>/dev/null
	[ $rc -eq 137 ] && echo "Zeitlimit von $secs s ueberschritten, abgebrochen" >> "$err"
	return $rc
}

# Text als JSON-Stringinhalt (ohne Anfuehrungszeichen): \ " Tab Zeilenumbruch, andere
# Steuerzeichen fallen weg
json_string() {
	tr -d '\000-\010\013\014\016-\037' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\r/\\r/g' -e "s/$TAB/\\\\t/g" |
		awk 'BEGIN{ORS=""} NR>1{print "\\n"} {print}'
}

# Antwort ablegen: reply <base> <json-zeilen oder ""> <fehlertext-datei oder "">
# JSON {ok, rows, err} -> base64url -> Stuecke zu 240 Zeichen -> Dateinamen in <base>.r
reply() {
	{
		if [ -n "$3" ]; then
			printf '{"ok":0,"rows":[],"err":"'
			json_string < "$3"
			printf '"}'
		else
			printf '{"ok":1,"err":"","rows":'
			if [ -n "$2" ] && [ -s "$2" ]; then cat "$2"; else printf '[]'; fi
			printf '}'
		fi
	} > "$1.json"
	rm -rf "$1.rtmp"
	mkdir "$1.rtmp" || return 1
	# awk + xargs statt einer read-Schleife: BusyBox liest aus der Pipe Byte fuer Byte
	# (1,6 MB: 28 s statt 1 s); die Namen enthalten nur [0-9A-Za-z_/-], xargs darf sie teilen
	base64 -w 0 < "$1.json" | tr '+/' '-_' | fold -w 240 |
		awk -v d="$1.rtmp" '{ printf "%s/%d_%s\n", d, NR + 9999, $0 }' | xargs -r touch
	mv "$1.rtmp" "$1.r" && : > "$1.rdy"
	rm -f "$1.json"
}

fail() {   # fail <base> <text>
	echo "$2" > "$1.err"
	reply "$1" "" "$1.err"
	rm -f "$1.sql" "$1.go" "$1.out" "$1.err"
}

free_kb() {
	df -k "$EVIL" 2>/dev/null | awk 'NR==2{print $4}'
}

file_kb() {
	[ -e "$1" ] && du -k "$1" | awk '{print $1}' || echo 0
}

# Sicherung anlegen; Rueckgabe 0 = ok, sonst Fehlertext auf stdout
backup() {
	mkdir -p "$STATE" || { echo "Sicherungsordner nicht anlegbar"; return 1; }
	need=$(( $(file_kb "$DB") + 2048 ))
	have=$(( $(free_kb) + $(file_kb "$BAK") ))
	if [ "$have" -lt "$need" ]; then
		echo "zu wenig Platz fuer die Sicherung ($have KB frei, $need KB noetig)"
		return 1
	fi
	rm -f "$BAK.tmp"
	if run_tmo $T_BACKUP /dev/null /dev/null "$DIR/backup.err" \
			"$SQLITE" -cmd ".timeout 5000" "file:$DB?mode=ro" ".backup '$BAK.tmp'"; then
		mv "$BAK.tmp" "$BAK" && rm -f "$WRITTEN" && sync
		log "Sicherung angelegt: $BAK ($(file_kb "$BAK") KB)"
		return 0
	fi
	rm -f "$BAK.tmp"
	echo "Sicherung fehlgeschlagen: $(cat "$DIR/backup.err")"
	return 1
}

# Lese-Anfrage (-safe: der Lesekanal schreibt keine Dateien und startet keine Shell)
answer_read() {
	base="$1"
	if run_tmo $T_READ "$base.sql" "$base.out" "$base.err" \
			"$SQLITE" -safe -readonly -json -cmd ".timeout 3000" "file:$DB?mode=ro"; then
		reply "$base" "$base.out" ""
	else
		reply "$base" "" "$base.err"
	fi
	rm -f "$base.sql" "$base.go" "$base.out" "$base.err"
}

# Schreib-Anfrage: eine Transaktion, Abbruch beim ersten Fehler (-bail -> rollback)
answer_write() {
	base="$1"
	if [ ! -e "$DIR/backup-done" ]; then
		# erste Schreibanfrage seit dem Start: vorher sichern
		if ! msg=$(backup); then
			fail "$base" "$msg"
			return
		fi
		touch "$DIR/backup-done"
	fi
	touch "$WRITTEN"
	{
		echo "pragma foreign_keys = on;"
		echo "begin immediate;"
		cat "$base.sql"
		echo ";"
		echo "select total_changes() as changes;"
		echo "commit;"
	} > "$base.tx"
	if run_tmo $T_WRITE "$base.tx" "$base.out" "$base.err" \
			"$SQLITE" -safe -bail -json -cmd ".timeout 3000" "$DB"; then
		sync
		reply "$base" "$base.out" ""
	else
		reply "$base" "" "$base.err"
	fi
	rm -f "$base.sql" "$base.go" "$base.tx" "$base.out" "$base.err"
}

# Shell-Anfrage: Skript als root, Ausgabe (stdout + stderr) und Exit-Code
answer_shell() {
	base="$1"
	run_tmo $T_SHELL /dev/null "$base.out" "$base.err" sh -c 'sh "$1" 2>&1' shell "$base.sql"
	rc=$?
	cat "$base.err" >> "$base.out"
	{
		printf '[{"rc":%d,"out":"' "$rc"
		json_string < "$base.out"
		# json_string verliert den letzten Zeilenumbruch - die Ausgabe soll ihn behalten
		[ -s "$base.out" ] && [ "$(tail -c 1 "$base.out" | od -An -tx1 | tr -d ' ')" = "0a" ] && printf '\\n'
		printf '"}]'
	} > "$base.rows"
	reply "$base" "$base.rows" ""
	rm -f "$base.sql" "$base.go" "$base.out" "$base.err" "$base.rows"
}

# Aktionen
answer_action() {
	base="$1"
	act=$(head -n 1 "$base.sql" | tr -d '\r\n ')
	case "$act" in
	status)
		bak_kb=$(file_kb "$BAK")
		bak_age=-1
		[ -e "$BAK" ] && bak_age=$(( $(date +%s) - $(date -r "$BAK" +%s 2>/dev/null || echo 0) ))
		[ -e "$WRITTEN" ] && written=1 || written=0
		[ -e "$BAD" ] && bad=1 || bad=0
		crashes=$(cat "$CRASHES" 2>/dev/null || echo 0)
		echo "[{\"db_kb\":$(file_kb "$DB"),\"free_kb\":$(free_kb),\"backup_kb\":$bak_kb,\"backup_age\":$bak_age,\"written\":$written,\"bad\":$bad,\"crashes\":$crashes,$(nam_json),\"version\":\"@VERSION@\"}]" > "$base.out"
		reply "$base" "$base.out" ""
		;;
	nam-on|nam-off)
		if [ ! -e "$NAM_LIB" ]; then
			echo "NAM-Mod ist in dieser Firmware nicht enthalten" > "$base.err"
			reply "$base" "" "$base.err"
		else
			mkdir -p "$STATE"
			if [ "$act" = nam-on ]; then rm -f "$NAM_OFF"; else echo manuell > "$NAM_OFF"; fi
			sync
			log "NAM ${act#nam-} (App-Neustart)"
			echo "[{$(nam_json),\"restarting\":1}]" > "$base.out"
			reply "$base" "$base.out" ""
			restart_app
		fi
		;;
	backup)
		if msg=$(backup); then
			echo "[{\"backup_kb\":$(file_kb "$BAK")}]" > "$base.out"
			touch "$DIR/backup-done"
			reply "$base" "$base.out" ""
		else
			echo "$msg" > "$base.err"
			reply "$base" "" "$base.err"
		fi
		;;
	restore)
		if [ ! -e "$BAK" ]; then
			echo "keine Sicherung vorhanden" > "$base.err"
			reply "$base" "" "$base.err"
		else
			mkdir -p "$STATE"
			touch "$RESTORE"
			echo '[{"restarting":1}]' > "$base.out"
			reply "$base" "$base.out" ""
			restart_app
		fi
		;;
	restart)
		echo '[{"restarting":1}]' > "$base.out"
		reply "$base" "$base.out" ""
		restart_app
		;;
	diag)
		# Diagnose auf Anfrage (bis 0.5 bei jedem Start): Datei auf dem USB-Laufwerk des Geraets
		if run_tmo $T_SHELL /dev/null "$base.out" "$base.err" "$DIAG" manual && [ -s "$base.out" ]; then
			printf '[{"file":"' > "$base.rows"
			head -n 1 "$base.out" | json_string >> "$base.rows"
			printf '"}]' >> "$base.rows"
			reply "$base" "$base.rows" ""
		else
			echo "Diagnose nicht geschrieben (USB-Laufwerk nicht eingehaengt?) $(cat "$base.err")" > "$base.err"
			reply "$base" "" "$base.err"
		fi
		rm -f "$base.rows"
		;;
	*)
		echo "unbekannte Aktion: $act" > "$base.err"
		reply "$base" "" "$base.err"
		;;
	esac
	rm -f "$base.sql" "$base.go" "$base.out" "$base.err"
}

# NAM-Zustand als JSON-Felder (ohne Klammern): nam_installed, nam_on (beim naechsten Start),
# nam_active (laufende App), nam_auto_off (vom Absturzwaechter abgeschaltet), nam_ref (Version)
nam_json() {
	if [ ! -e "$NAM_LIB" ]; then
		printf '"nam_installed":0,"nam_on":0,"nam_active":0,"nam_auto_off":0,"nam_ref":""'
		return
	fi
	[ -e "$NAM_OFF" ] && on=0 || on=1
	[ -e "$NAM_ACTIVE" ] && active=1 || active=0
	[ "$(cat "$NAM_OFF" 2>/dev/null)" = auto ] && auto=1 || auto=0
	ref=$(sed -n 's/^nam_mod_ref=//p' "$NAM_INFO" 2>/dev/null | head -n 1 | json_string)
	printf '"nam_installed":1,"nam_on":%s,"nam_active":%s,"nam_auto_off":%s,"nam_ref":"%s"' \
		$on $active $auto "$ref"
}

# Vor dem App-Start (aus evil, nach prestart): mit NAM starten? Merkt sich die Antwort fuer
# postexit und status.
nam_start() {
	mkdir -p "$DIR"
	if [ -e "$NAM_LIB" ] && [ ! -e "$NAM_OFF" ]; then
		touch "$NAM_ACTIVE"
		return 0
	fi
	rm -f "$NAM_ACTIVE"
	return 1
}

# App beenden; die Startschleife (evil) startet sie neu. Der Marker verhindert,
# dass ein Ende mit Exit-Code 0 als Ausschaltwunsch verstanden wird.
restart_app() {
	read -t 1 x <&7   # Antwort erst zur QML durchlassen
	touch "$RESTART"
	log "App-Neustart angefordert"
	for p in /proc/[0-9]*; do
		[ "$(cat "$p/comm" 2>/dev/null)" = "Evil" ] && kill -TERM "${p#/proc/}"
	done
}

# Vor dem App-Start (aus /usr/Evil/Scripts/evil): Wiederherstellung
prestart() {
	mkdir -p "$DIR"
	if [ -e "$RESTORE" ]; then
		rm -f "$RESTORE"
		if [ -e "$BAK" ]; then
			log "Datenbank wird aus der Sicherung wiederhergestellt"
			rm -f "$BAD"
			mv "$DB" "$BAD" 2>/dev/null
			mv "$DB-journal" "$BAD-journal" 2>/dev/null
			if cp "$BAK" "$DB"; then
				rm -f "$WRITTEN" "$CRASHES"
				sync
				log "Wiederherstellung fertig"
			else
				log "Wiederherstellung fehlgeschlagen - alte Datenbank bleibt"
				mv "$BAD" "$DB" 2>/dev/null
			fi
		else
			log "Wiederherstellung angefordert, aber keine Sicherung vorhanden"
		fi
	fi
}

# Nach dem App-Ende: Absturzschleife erkennen
postexit() {
	code="$1"; start="$2"
	mkdir -p "$DIR"
	[ -e "$RESTART" ] && { rm -f "$CRASHES"; return; }
	now=$(date +%s)
	if [ "$code" != "0" ] && [ $(( now - start )) -lt "$CRASH_SECS" ]; then
		n=$(( $(cat "$CRASHES" 2>/dev/null || echo 0) + 1 ))
		echo "$n" > "$CRASHES"
		log "App kurz nach dem Start beendet (Code $code), $n. Mal in Folge"
		if [ "$n" -ge "$CRASH_MAX" ] && [ -e "$NAM_ACTIVE" ]; then
			log "Absturzschleife mit NAM - NAM wird abgeschaltet (nam-on schaltet es wieder ein)"
			mkdir -p "$STATE"
			echo auto > "$NAM_OFF"
			sync
			rm -f "$CRASHES"
		elif [ "$n" -ge "$CRASH_MAX" ] && [ -e "$WRITTEN" ] && [ -e "$BAK" ]; then
			log "Absturzschleife nach Bridge-Schreibzugriff - Sicherung wird zurueckgespielt"
			touch "$RESTORE"
			rm -f "$CRASHES"
		fi
	else
		rm -f "$CRASHES"
	fi
}

TAB=$(printf '\t')

case "$1" in
daemon)
	exec 8>"$LOCK"
	flock -n 8 || exit 0
	mkdir -p "$DIR"
	rm -rf "$DIR"/q* "$DIR"/w* "$DIR"/a* "$DIR"/s* "$TICK"
	mkfifo "$TICK" && exec 7<> "$TICK" || exit 1
	log "Datenbankdienst @VERSION@ gestartet"
	quiet=0
	while :; do
		busy=0
		for go in "$DIR"/q*.go "$DIR"/w*.go "$DIR"/a*.go "$DIR"/s*.go; do
			[ -e "$go" ] || continue
			busy=1
			base="${go%.go}"
			case "${base##*/}" in
			q*) answer_read "$base" ;;
			w*) answer_write "$base" ;;
			a*) answer_action "$base" ;;
			s*) answer_shell "$base" ;;
			esac
		done
		for done in "$DIR"/q*.done "$DIR"/w*.done "$DIR"/a*.done "$DIR"/s*.done; do
			[ -e "$done" ] || continue
			rm -rf "${done%.done}".*
		done
		# 40 ms, solange Anfragen kommen (bis 5 s danach), sonst 100 ms - ohne Prozessstart
		if [ $busy -eq 1 ]; then quiet=0; elif [ $quiet -lt 125 ]; then quiet=$((quiet + 1)); fi
		if [ $quiet -lt 125 ]; then read -t 0.04 x <&7; else read -t 0.1 x <&7; fi
	done
	;;
prestart)
	prestart
	;;
nam)
	nam_start
	;;
postexit)
	postexit "$2" "$3"
	;;
*)
	echo "Aufruf: $0 daemon | prestart | nam | postexit <code> <start>" >&2
	exit 2
	;;
esac
