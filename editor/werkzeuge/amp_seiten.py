"""Liest am Geraet fuer jedes Amp-Modell die Reglerseite und schreibt modellseiten.json.

Jedes Amp-Modell nutzt nur einen Teil der Amp-Parameter (GainA, Bright, JCDistortion, ...),
unter eigener Beschriftung. Das Geraet zeigt die Seite des Blocks, auf dem RedirCtrl/CurModule
steht: RedirCtrl/ParamName<k> = Beschriftung ("" = unbenutzt), ParamRedirected<k>.path =
der echte Parameterpfad. Das Werkzeug laedt das Test-Rig MXBRIDGE TEST (Setlist GHOST),
schaltet Amp/Type durch alle Modelle und verwirft die Aenderungen danach (~30 s).
Haelfte B (Type2) hat dieselben Seiten mit Endung 2 (Tremolo/TremSync gemeinsam), 2026-09-29 geprueft.

Aufruf (aus dem Editor-Ordner): python werkzeuge\\amp_seiten.py
"""
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from bridge import Bridge
import live as L

TEST_RIG, TEST_SET = "MXBRIDGE TEST", "GHOST"
OUT = os.path.join(os.path.dirname(HERE), "modellseiten.json")
JS = ("var o=[]; for (var k=1;k<=16;k++){var n=App.getProperty('/Engine/RedirCtrl/ParamName'+k).translator.string;"
      "if(n) o.push(n+'='+App.getProperty('/Engine/RedirCtrl/ParamRedirected'+k).path.split('/').pop());}"
      " return o.join('|');")


def main():
    br = Bridge.auto()
    print(br.ping())
    st = L.rig_status(br)
    if st["name"] != TEST_RIG:
        if st["dirty"]:
            sys.exit("Das geladene Rig '%s' hat ungespeicherte Aenderungen - bitte erst speichern oder verwerfen." % st["name"])
        res = L.read_rig_list(br)
        if res["setlist"] != TEST_SET:
            res = L.enter_setlist(br, res["setlists"], TEST_SET, res["setlist_ids"])
        names = [L.display_name(r["name"]) for r in res["rows"]]
        st = L.load_rig(br, res["rows"], names.index(TEST_RIG))
        assert st["name"] == TEST_RIG, st["name"]
    rows = L.read_rig_list(br)["rows"]
    chain = [br.get("/Engine/Patch/Chain/ModuleType%d" % k).get("string") for k in range(1, 12)]
    try:
        if "Amp" not in chain:
            k = chain.index(L.EMPTY) + 1
            br.set("/Engine/Patch/Chain/ModuleType%d" % k, "user", "Amp")
            time.sleep(0.6)
            chain[k - 1] = "Amp"
        br.set("/Engine/RedirCtrl/CurModule", "index", chain.index("Amp") + 1)   # Eintraege: Input, 1..11, ...
        time.sleep(0.3)
        pages = {}
        for i, model in enumerate(br.entries("/Engine/Patch/Amp/Type")):
            br.set("/Engine/Patch/Amp/Type", "index", i)
            time.sleep(0.25)
            assert br.get("/Engine/Patch/Amp/Type").get("string") == model
            pages[model] = [x.split("=", 1) for x in br.eval(JS).split("|") if x]
            print(model, pages[model])
    finally:
        st = L.reload_rig(br, rows)
        print("Test-Rig neu geladen:", st["name"], "geaendert" if st["dirty"] else "unveraendert")
    lines = ['{', ' "quelle": "MX5 Firmware 2.7, RedirCtrl/ParamName + ParamRedirected je Modell (werkzeuge/amp_seiten.py)",',
             ' "Amp": {']
    items = list(pages.items())
    for n, (model, rows) in enumerate(items):
        lines.append('  %s: %s%s' % (json.dumps(model, ensure_ascii=False), json.dumps(rows, ensure_ascii=False),
                                      "," if n < len(items) - 1 else ""))
    lines += [' }', '}', '']
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print("%d Modelle -> %s" % (len(pages), OUT))


if __name__ == "__main__":
    main()
