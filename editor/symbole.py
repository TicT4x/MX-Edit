"""symbole.py - Flache 2D-Symbole fuer alle Modelle des MX5 (Amps, Boxen, Effekte).

Jedes Modell bekommt eine kleine Beschreibung (Form + Farben + Details), die
mit Pillow gezeichnet wird. Die Formen sind an die Produktbilder der
HeadRush-Website angelehnt (werkzeuge/symbole_laden.py laedt sie als Vorlage),
aber bewusst reduziert: nur Flaechen, keine Verlaeufe, damit das Original
trotzdem erkennbar bleibt (Tweed-Fender, Blackface, Plexi, Boss-Treter, ...).

Formen:
  head   Amp-Kopf (breit): Gehaeuse, Bedienfeld oben/unten/ganzflaechig, Bespannung, Knoepfe
  combo  Combo/Box mit Bedienfeld oben und Lautsprechern
  cab    Box ohne Bedienfeld (optional schraeg = Marshall-Slant)
  pedal  Bodentreter (hochkant); Varianten wide, big, boss (dunkle Trittplatte)
  round  runder Treter (Fuzz Face)
  drop   HeadRush-Tropfenform (Ambi Verb, Reso Delay)
  rack   19"-Geraet (flach)
  wah    Wippe hochkant (Wah, Volume)
  wham   Wippe breit mit Platte (Whammy)
  jack / mix   Werkzeuge (FX-Loop, Mix)

zeichnen(dr, W, H, look) malt in ein W x H grosses Bild (Seitenverhaeltnis 10:7).
look_for(name, model) sucht die Beschreibung zu einem Blocknamen (+ Amp-/Cab-Modell).
"""

import math

# ---------------- Farben (flach) ----------------
BLACK = "#141416"
PANEL_BLK = "#101012"
GOLD = "#c9a24a"
CHROME = "#d4d5d8"
CREAM = "#ece8da"
TWEED = "#c8a75c"
SILVER_CLOTH = "#c4c2b8"
WHEAT = "#c9a765"
KNOB_BLK = "#1a1a1a"
KNOB_WHT = "#e2e2e4"
KNOB_SLV = "#cfcfd2"
LED_RED = "#e0443c"
LED_BLUE = "#3f8fe8"
LED_GRN = "#3fae49"
LOGO_WHT = "#e6e6e8"
RACK = "#26272c"
SCREEN_BLUE = "#3f7fd9"
FOOT = "#c8c9cc"
FOOT_EDGE = "#3a3b40"
OUTLINE = "#0a0a0c"

# Gemeinsame Bausteine
BLACKFACE = dict(form="head", body="#1c1c1f", panel=PANEL_BLK, panel_pos="top", knob=KNOB_SLV, grille=SILVER_CLOTH,
                 tex="lines", logo=LOGO_WHT)
PLEXI = dict(form="head", body=BLACK, panel=GOLD, panel_pos="bottom", knob=KNOB_BLK, grille="#1f1f22", logo=LOGO_WHT)
RACK_BLUE = dict(form="rack", body=RACK, knob=KNOB_SLV, screen=SCREEN_BLUE, knobs=8)
BOSS = dict(form="pedal", boss=True, knob=KNOB_BLK, led=LED_RED)


def _d(base, **kw):
    d = dict(base)
    d.update(kw)
    return d


# ---------------- Amp-Modelle (Amp/Type) ----------------
AMPS = {
    "59 tweed bass": dict(form="head", body=TWEED, panel=CHROME, panel_pos="bottom", knob=KNOB_BLK, grille=TWEED,
                          tex="weave", knobs=6),
    "59 tweed deluxe": dict(form="head", body=TWEED, panel=CHROME, panel_pos="bottom", knob=KNOB_BLK, grille=TWEED,
                            tex="weave", knobs=3),
    "59 deluxe gain mod": dict(form="head", body=TWEED, panel=CHROME, panel_pos="bottom", knob=KNOB_BLK,
                               grille="#6b4a2e", tex="lines", knobs=5),
    "59 tweed prince": dict(form="head", body=TWEED, panel=CHROME, panel_pos="bottom", knob=KNOB_BLK, grille=TWEED,
                            tex="weave", knobs=3, led=LED_RED),
    "64 black lux norm": _d(BLACKFACE, knobs=6),
    "64 black lux vib": _d(BLACKFACE, knobs=6),
    "64 black vib": _d(BLACKFACE, knobs=6),
    "65 black mini": _d(BLACKFACE, grille="#c9b98a", knobs=3),
    "65 black prince": _d(BLACKFACE, grille="#a8adb8", knobs=4),
    "65 black prince rev": _d(BLACKFACE, grille="#a8adb8", knobs=6),
    "65 black sr": _d(BLACKFACE, knobs=8),
    "67 black duo": _d(BLACKFACE, grille="#cfcdc4", knobs=10),
    "67 black shimmer": dict(form="head", body="#111113", panel=PANEL_BLK, panel_pos="mid", knob=KNOB_WHT, knobs=8,
                             logo=LOGO_WHT),
    "66 ac hi boost": dict(form="head", body="#1a1a1c", panel="#3f8b94", panel_pos="bottom", knob=KNOB_BLK,
                           grille="#1e1e22", tex="diamond", knobs=6, logo=LOGO_WHT),
    "66 ac hi boost mod": dict(form="head", body="#a9783f", panel="#212125", panel_pos="bottom", knob=KNOB_WHT,
                               grille=WHEAT, tex="weave", knobs=6, logo=LOGO_WHT),
    "66 flip bass": dict(form="head", body="#1e2a44", panel="#161c30", panel_pos="bottom", knob=KNOB_WHT,
                         grille="#2c3d63", tex="diamond", knobs=5, logo="#3b73d1"),
    "69 blue line bass": dict(form="head", body="#1c1c1f", panel="#b9c3d1", panel_pos="top", knob=KNOB_WHT,
                              grille="#8797b0", tex="weave", knobs=9),
    "69 blue line scoop": dict(form="head", body="#1c1c1f", panel="#b9c3d1", panel_pos="top", knob=KNOB_WHT,
                               grille="#8797b0", tex="weave", knobs=9),
    "65 j45": _d(PLEXI, knobs=6, logo="#d4af37"),
    "67 plexiglas vari": _d(PLEXI, knobs=8),
    "68 plexi el84 mod": _d(PLEXI, body="#a97a3c", grille="#c99a55", tex="weave", knobs=8),
    "69 plexiglas 100w": _d(PLEXI, knobs=8),
    "68 plexiglas 50w": _d(PLEXI, knobs=7, logo="#d4af37"),
    "82 lead 800 100w": _d(PLEXI, knobs=8, tag=LOGO_WHT),
    "82 lead 800 50w": _d(PLEXI, knobs=7, tag=LOGO_WHT),
    "82 lead 800 bass mod": _d(PLEXI, panel="#232326", knob="#2a2a2e", knob_line="#8a8a8e", knobs=8),
    "82 lead 800 bright": _d(PLEXI, panel="#232326", knob="#2a2a2e", knob_line="#8a8a8e", knobs=8),
    "82 lead 800 ts mod": _d(PLEXI, knobs=8, tag=LOGO_WHT),
    "83 400r": dict(form="head", body=RACK, panel="#3b3c42", panel_pos="mid", knob=KNOB_SLV, knobs=8, hgt=30,
                    logo=LOGO_WHT),
    "84 j-120h": dict(form="head", body="#8c8d92", panel="#1f1f22", panel_pos="mid", knob=KNOB_SLV, knobs=10),
    "85 m-2 lead": dict(form="head", body="#161618", panel="#26272c", panel_pos="mid", knob=KNOB_SLV, knobs=10,
                        logo=LOGO_WHT),
    "85 m-2 lead cap mod": dict(form="head", body="#161618", panel="#26272c", panel_pos="mid", knob=KNOB_SLV,
                                knobs=10, logo=LOGO_WHT),
    "92 treadplate modern": dict(form="head", body=BLACK, panel="#1a1a1d", panel_pos="bottom", knob=KNOB_SLV,
                                 grille="#9a9ca2", tex="diamond", knobs=9, logo="#1a1a1d"),
    "92 treadplate raw": dict(form="head", body=BLACK, panel="#1a1a1d", panel_pos="bottom", knob=KNOB_SLV,
                              grille="#9a9ca2", tex="diamond", knobs=9, logo="#1a1a1d"),
    "92 treadplate vintage": dict(form="head", body=BLACK, panel="#1a1a1d", panel_pos="bottom", knob=KNOB_SLV,
                                  grille="#9a9ca2", tex="diamond", knobs=9, logo="#1a1a1d"),
    "93 ms30": dict(form="head", body=BLACK, panel=CREAM, panel_pos="top", panel_h=24, knob=KNOB_BLK, knobs=8,
                    grille="#151517", logo="#e0b040"),
    "99 pv51 ii clean": dict(form="head", body=BLACK, panel="#e8e8ea", panel_pos="bottom", knob=KNOB_BLK, knobs=8,
                             grille="#1f1f22", logo=LOGO_WHT),
    "99 pv51 ii crunch": dict(form="head", body=BLACK, panel="#e8e8ea", panel_pos="bottom", knob=KNOB_BLK, knobs=8,
                              grille="#1f1f22", logo=LOGO_WHT),
    "99 pv51 ii lead": dict(form="head", body=BLACK, panel="#e8e8ea", panel_pos="bottom", knob=KNOB_BLK, knobs=8,
                            grille="#1f1f22", logo=LOGO_WHT),
    "97 rb-01b green": dict(form="head", body=BLACK, panel=PANEL_BLK, panel_pos="bottom", knob=KNOB_SLV, knobs=8,
                            grille="#b58a5a", tex="weave", led=LED_GRN, logo=LOGO_WHT),
    "97 rb-01b blue": dict(form="head", body=BLACK, panel=PANEL_BLK, panel_pos="bottom", knob=KNOB_SLV, knobs=8,
                           grille="#b58a5a", tex="weave", led=LED_BLUE, logo=LOGO_WHT),
    "97 rb-01b red": dict(form="head", body=BLACK, panel=PANEL_BLK, panel_pos="bottom", knob=KNOB_SLV, knobs=8,
                          grille="#b58a5a", tex="weave", led=LED_RED, logo=LOGO_WHT),
    "89 sl-100 clean": dict(form="head", body=BLACK, panel=CREAM, panel_pos="bottom", knob=KNOB_BLK, knobs=8,
                            grille="#1f1f22", tex="diamond", logo=LOGO_WHT),
    "89 sl-100 crunch": dict(form="head", body=BLACK, panel=CREAM, panel_pos="bottom", knob=KNOB_BLK, knobs=8,
                             grille="#1f1f22", tex="diamond", logo=LOGO_WHT),
    "89 sl-100 drive": dict(form="head", body=BLACK, panel=CREAM, panel_pos="bottom", knob=KNOB_BLK, knobs=8,
                            grille="#1f1f22", tex="diamond", logo=LOGO_WHT),
    "89 sl-100 ext range": dict(form="head", body=BLACK, panel="#1c1c1f", panel_pos="top", knob=KNOB_SLV, knobs=9,
                                grille="#151517", logo=LOGO_WHT),
    "05 tangerine 30 ch1": dict(form="head", body="#e8731c", panel="#efe9d8", panel_pos="bottom", knob=KNOB_BLK,
                                knobs=6, logo="#f4f4f4"),
    "05 tangerine 30 ch2": dict(form="head", body="#e8731c", panel="#efe9d8", panel_pos="bottom", knob=KNOB_BLK,
                                knobs=6, logo="#f4f4f4", led=LED_RED),
    "11 epb ii clean": dict(form="head", body=BLACK, panel="#1c1c1f", panel_pos="bottom", knob=KNOB_SLV, knobs=10,
                            grille="#2a2b30", tex="diamond", logo=LOGO_WHT),
    "11 epb ii crunch": dict(form="head", body=BLACK, panel="#1c1c1f", panel_pos="bottom", knob=KNOB_SLV, knobs=10,
                             grille="#2a2b30", tex="diamond", logo=LOGO_WHT),
    "11 epb ii lo-lead": dict(form="head", body=BLACK, panel="#1c1c1f", panel_pos="bottom", knob=KNOB_SLV, knobs=10,
                              grille="#2a2b30", tex="diamond", logo=LOGO_WHT),
    "11 epb ii hi-lead": dict(form="head", body=BLACK, panel="#1c1c1f", panel_pos="bottom", knob=KNOB_SLV, knobs=10,
                              grille="#2a2b30", tex="diamond", logo=LOGO_WHT),
    "17 trace elliot elf": dict(form="head", body="#1c1c1f", panel="#1c1c1f", panel_pos="mid", knob=KNOB_SLV, knobs=4,
                                hgt=26, led=LED_GRN, logo=LED_GRN),
}

# ---------------- Boxen (Cab/CabType) ----------------
CABS = {
    "1x8 custom": dict(form="combo", body="#1a1a1c", panel=PANEL_BLK, knob=KNOB_SLV, knobs=3, grille=SILVER_CLOTH,
                       tex="lines", spk=1, w=44, h=42),
    "1x12 black panel lux": dict(form="combo", body="#1a1a1c", panel=PANEL_BLK, knob=KNOB_SLV, knobs=6,
                                 grille=SILVER_CLOTH, tex="lines", spk=1, w=52, h=56),
    "1x12 tweed lux": dict(form="combo", body=TWEED, panel=CHROME, knob=KNOB_BLK, knobs=3, grille="#6b4a2e",
                           tex="lines", spk=1, w=52, h=56),
    "1x15 open back": dict(form="combo", body="#243a5e", panel="#1c2c48", knob=KNOB_WHT, knobs=3, grille="#c9c4ae",
                           tex="lines", spk=1, w=56, h=58),
    "2x12 ac blue": dict(form="combo", body="#1a1a1c", panel="#1e1e22", knob=KNOB_WHT, knobs=6, grille="#b88a52",
                         tex="diamond", spk=2, w=60, h=56, logo=LOGO_WHT),
    "2x12 black panel duo": dict(form="combo", body="#1a1a1c", panel=PANEL_BLK, knob=KNOB_SLV, knobs=10,
                                 grille="#cfcdc4", tex="lines", spk=2, w=62, h=54),
    "2x12 b30": dict(form="combo", body="#1a1a1c", panel="#1a1a1c", knob=None, knobs=0, grille="#c2ab7a",
                     tex="weave", spk=2, w=60, h=52, logo=LOGO_WHT),
    "2x12 silver cone": dict(form="combo", body="#1a1a1c", panel="#1a1a1c", knob=None, knobs=0, grille="#9c9ea3",
                             tex="lines", spk=2, w=60, h=52, logo=LOGO_WHT),
    "4x10 tweed bass": dict(form="combo", body=TWEED, panel=CHROME, knob=KNOB_BLK, knobs=6, grille="#6b4a2e",
                            tex="lines", spk=4, w=56, h=60),
    "4x10 black sr": dict(form="combo", body="#1a1a1c", panel=PANEL_BLK, knob=KNOB_SLV, knobs=8, grille="#c8c6bd",
                          tex="lines", spk=4, w=56, h=60),
    "4x12 classic 30w": dict(form="cab", body=BLACK, grille="#1f1f22", tex="diamond", spk=4, slant=True, w=56, h=62,
                             logo=LOGO_WHT),
    "4x12 65w": dict(form="cab", body=BLACK, grille="#1f1f22", tex="diamond", spk=4, slant=True, w=56, h=62,
                     logo=LOGO_WHT, tag=LED_GRN),
    "4x12 green 25w": dict(form="cab", body=BLACK, grille=WHEAT, tex="weave", spk=4, slant=True, w=56, h=62,
                           logo=LOGO_WHT),
    "4x12 green 20w": dict(form="cab", body=BLACK, grille="#9c9ea3", tex="lines", spk=4, slant=True, w=56, h=62,
                           logo=LOGO_WHT),
    "8x10 blue line": dict(form="cab", body=BLACK, grille="#8797b0", tex="weave", spk=8, w=44, h=66, logo=LOGO_WHT),
}
IR_LOOK = dict(form="cab", body=RACK, grille="#3a3b41", spk=0, w=50, h=54, wave="#1fc9a1")

# ---------------- Effekt-Bloecke (Basisname) ----------------
FX = {
    # Overdrive
    "green jrc-od": dict(form="pedal", body="#3f9a4a", knob=KNOB_BLK, knobs="3", plate="#cfd0d3"),
    "white boost": dict(form="pedal", body="#e6e6e8", knob=KNOB_BLK, knobs="4", led=LED_BLUE),
    "anxiety od": dict(form="pedal", body="#e8e8ea", knob=KNOB_BLK, knobs="2+1", sw=True),
    "anxiety od v2": dict(form="pedal", body="#dcdcdf", knob=KNOB_BLK, knobs="2+1", sw=True),
    # NAM-Mod im Anxiety OD: Amp-Topteil (es ersetzt einen Amp), auf der Bespannung ein kleines
    # neuronales Netz statt Stoff (Symbol ueber das Feld 'icon' der Kette, kein Blockname des Geraets)
    "nam": dict(form="nam", body="#1c2331", panel="#2b3548", grille="#0f141d", knob=KNOB_WHT, knobs=3,
                net="#35d0c0", logo="#35d0c0", led="#35d0c0"),
    "s1 drive": _d(BOSS, body="#e2b33c", knobs="3"),
    "b2 drive": _d(BOSS, body="#3f7fd9", knobs="3"),
    "d250 drive": dict(form="pedal", body="#e8c93a", knob=KNOB_WHT, knobs="2", band=(BLACK, 30, 46), led=LED_BLUE),
    "k drive": dict(form="pedal", wide=True, body="#e8a23c", knob=KNOB_BLK, knobs="3"),
    "glorious drive": dict(form="pedal", big=True, body="#c9b56a", knob="#efefef", knobs="2+1", led=LED_BLUE),
    # Distortion / Fuzz
    "tri fuzz": dict(form="pedal", body="#a8a9ad", knob=KNOB_BLK, knobs="3", band=("#c0392b", 36, 46)),
    "b dist 7000": dict(form="pedal", wide=True, body="#1a1a1c", knob="#2a2a2e", knob_line="#8a8a8e", knobs="6",
                        led=LED_BLUE, line="#5a5b60"),
    "oct fuzz": dict(form="pedal", body="#e8e8ea", knob=KNOB_BLK, knobs="2s"),
    "d1 dist": _d(BOSS, body="#ee8a2a", knobs="3"),
    "round fuzz": dict(form="round", body="#a3332b", knob=KNOB_BLK),
    "mx dist": dict(form="pedal", body="#e8c93a", knob=KNOB_BLK, knobs="2"),
    "black op": dict(form="pedal", body="#1a1a1c", knob="#2a2a2e", knob_line="#8a8a8e", knobs="3",
                     band=("#e8e8ea", 34, 42)),
    "dc distort": dict(form="pedal", body="#f0a05a", knob=KNOB_BLK, knobs="4"),
    "8-bit crush": dict(form="pedal", body="#3a2a24", knob=KNOB_BLK, knob_line="#6a6a6e", knobs="4",
                        frame="#8a5a3a"),
    # EQ
    "bass eq": dict(form="pedal", body="#7a7d84", knob=KNOB_BLK, knobs="2+1", band=("#c0392b", 38, 46), boss=True,
                    led=LED_RED),
    "graphic eq": dict(form="pedal", body="#2b6fb5", knobs="0", sliders=7),
    "ten freq eq": dict(form="pedal", body="#3a3b41", knobs="0", sliders=10, led=LED_RED),
    "para eq": _d(RACK_BLUE, knobs=9),
    "acoustic pre": dict(form="pedal", body="#e8e8ea", knob=KNOB_BLK, knobs="3", led=LED_GRN),
    # Kompressor
    "gray comp": dict(form="pedal", body="#8c8d92", knob=KNOB_BLK, knobs="2"),
    "dyniii comp": _d(RACK_BLUE, knobs=6),
    "side comp": _d(RACK_BLUE, knobs=7),
    "sustain": dict(form="pedal", body="#d9443c", knob=KNOB_BLK, knobs="2"),
    # Delay
    "tape echo": dict(form="rack", body="#9a9ba0", knob="#2a2a2e", knobs=6, led=LED_RED),
    "time warp": dict(form="wham", body="#e8c93a", plate=BLACK, label="#e8c93a"),
    "reverse delay": _d(BOSS, body="#ece9dc", knob="#2fbfae", knobs="3"),
    "bbd delay": _d(BOSS, body="#9a9ba0", knobs="6"),
    "dyn delay": dict(form="rack", body="#6a6b70", knob=KNOB_BLK, knobs=8),
    "reso delay": dict(form="drop", body="#1a1a1c", deco="#ee8a2a", deco_kind="dots"),
    "air delay": _d(RACK_BLUE, knobs=10),
    "pitch delay": _d(BOSS, body="#3f7fd9", knob=KNOB_WHT, knobs="4s"),
    "hold": dict(form="pedal", body="#cfe3ee", knob=KNOB_BLK, knobs="4", led=LED_RED),
    # Reverb
    "air reverb": dict(form="pedal", body="#2f7fb5", knob=KNOB_BLK, knobs="4"),
    "eleven reverb": _d(RACK_BLUE, knobs=5),
    "spring reverb": _d(BOSS, body="#8c8d92", knobs="4", led=None),
    "shimmer": _d(BOSS, body="#3fa0e8", knobs="3", led="#e6c229"),
    "ambi verb": dict(form="drop", body="#1a1a1c", deco="#3f7fd9", deco_kind="waves"),
    "party verb": dict(form="pedal", body="#8a5ad6", knob=KNOB_BLK, knobs="3", led=LED_RED),
    # Chorus
    "chorus": dict(form="pedal", body="#cfd0d3", knob=KNOB_BLK, knobs="4", led=LED_RED),
    "multi chorus": _d(RACK_BLUE, knobs=9),
    "dim chorus": dict(form="rack", body="#3a3b41", knobs=0, buttons=4),
    "stereo doubler": dict(form="pedal", body="#d9d9d2", knob=KNOB_BLK, knobs="2+1"),
    # Phaser / Flanger
    "flanger": dict(form="pedal", body="#7a3f9a", knob=KNOB_BLK, knobs="4", led=LED_RED),
    "air flanger": dict(form="pedal", body="#8a4ab8", knob="#efefef", knobs="4"),
    "vibe phaser": dict(form="pedal", body="#1a1a1c", knob="#2a2a2e", knob_line="#8a8a8e", knobs="2", sw=True),
    "orange phaser": dict(form="pedal", body="#ee8a2a", knob=KNOB_BLK, knobs="1"),
    "tron phaser": dict(form="pedal", body="#3a9a4a", knob=KNOB_BLK, knobs="4", led=LED_RED),
    "stone phaser": dict(form="pedal", body="#8fd94a", knob=KNOB_BLK, knobs="4", led=LED_RED),
    # Vib / Trem / Rotary
    "vibrato": dict(form="pedal", body="#cfd0d3", knob=KNOB_BLK, knobs="4", led=LED_RED),
    "air vibrato": dict(form="pedal", body="#d9443c", knob=KNOB_BLK, knobs="4"),
    "rotary": dict(form="pedal", body="#1a1a1c", knob="#2a2a2e", knob_line="#8a8a8e", knobs="2", sw=True),
    "tremolo": _d(BOSS, body="#2fbfae", knobs="3"),
    "panner": dict(form="wah", body="#1a1a1c", frame="#c9cacd"),
    # Wah / Filter
    "shine wah": dict(form="wah", body="#1a1a1c", frame="#c9cacd"),
    "black wah": dict(form="wah", body="#1a1a1c"),
    "more wah": dict(form="wah", body="#1a1a1c", band="#c0392b"),
    "white bass wah": dict(form="wah", body="#e8e8ea"),
    "air filter": dict(form="pedal", body="#1a1a1c", knob="#2a2a2e", knob_line="#8a8a8e", knobs="4", frame="#8a5a3a",
                       led=LED_RED),
    "tron filter": dict(form="pedal", body="#ece9dc", knobs="0", band=("#3a2a7a", 4, 40), sw=True, led=LED_RED),
    "env filter": _d(BOSS, body="#2fa84a", knob="#d0d0d0", knobs="2"),
    # Pitch
    "wham": dict(form="wham", body="#d9443c", plate=BLACK, label="#e8e8ea"),
    "chord wham": dict(form="wham", body="#d9443c", plate=BLACK, label="#d9443c"),
    "harm": dict(form="wham", body="#d9443c", plate=BLACK, label="#e8e8ea"),
    "smart harm": _d(RACK_BLUE, knobs=10),
    "octaves": _d(BOSS, body="#5a3a34", knob="#2a2a2e", knob_line="#8a8a8e", knobs="2+1"),
    "octaves up": dict(form="pedal", body="#d9443c", knob=KNOB_BLK, knobs="2+1", led=LED_RED),
    "drop tune": dict(form="pedal", body="#d9443c", knob=KNOB_BLK, knobs="2+1", led="#e8e8ea"),
    "detune": dict(form="rack", body=RACK, knob=KNOB_SLV, knobs=8, screen="#d9443c"),
    "ring mod": dict(form="pedal", body="#1a1a1c", knob="#2a2a2e", knob_line="#8a8a8e", knobs="2+1", frame="#8a5a3a"),
    "feedback": dict(form="wham", body="#9a9ba0", plate=BLACK, label="#e8e8ea"),
    # Volume / Dynamik
    "volume": dict(form="wah", body="#1a1a1c", frame="#c9cacd"),
    "noise filter": dict(form="rack", body=RACK, knob=KNOB_SLV, knobs=6),
    "gate": dict(form="pedal", body="#2b6fb5", knob="#4fc3e8", knobs="3s", band=("#1a1a1c", 8, 20), led=LED_RED),
    "auto swell": dict(form="pedal", body="#3a3b41", knob="#e0e0e0", knobs="2+1", led=LED_RED),
    # Werkzeuge
    "acoust sim": _d(BOSS, body="#f0b14a", knobs="3"),
    "fx-loop": dict(form="jack"),
    "mix": dict(form="mix"),
    "chain": dict(form="mix"),      # Pseudo-Block "Parallelwege" des Editors
}
GENERIC = dict(form="pedal", body="#4a4d56", knob=KNOB_BLK, knobs="2")


def _norm(n):
    return " ".join((n or "").lower().split())


def look_for(name, model=None):
    """Beschreibung zu Block `name` (Basisname, z. B. 'Amp', 'Green JRC-OD') und ggf. Modell."""
    n = _norm(name)
    if n == "amp":
        return AMPS.get(_norm(model), _d(PLEXI, knobs=6))
    if n == "cab":
        return CABS.get(_norm(model), CABS["4x12 classic 30w"])
    if n in ("ir", "ir (1024)"):
        return IR_LOOK
    return FX.get(n, GENERIC)


# ---------------- Zeichnen ----------------
def zeichnen(dr, W, H, look):
    """look in ein W x H grosses Bild malen (Einheiten: Breite = 100, Hoehe = 70)."""
    u = W / 100.0
    form = look.get("form", "pedal")
    fn = {"head": _head, "combo": _cab, "cab": _cab, "pedal": _pedal, "round": _round, "drop": _drop,
          "rack": _rack, "wah": _wah, "wham": _wham, "jack": _jack, "mix": _mix,
          "nam": _nam}.get(form, _pedal)
    fn(_Pen(dr, u), look)


class _Pen:
    """Zeichenhilfe in Einheiten (0..100 x 0..70)."""

    def __init__(self, dr, u):
        self.dr, self.u = dr, u
        self.lw = max(1, int(round(1.2 * u)))

    def p(self, v):
        return v * self.u

    def rect(self, x0, y0, x1, y1, fill, r=0, outline=None, width=None):
        b = [self.p(x0), self.p(y0), self.p(x1), self.p(y1)]
        w = self.lw if width is None else max(1, int(round(width * self.u)))
        if r:
            self.dr.rounded_rectangle(b, radius=self.p(r), fill=fill, outline=outline, width=w if outline else 0)
        else:
            self.dr.rectangle(b, fill=fill, outline=outline, width=w if outline else 0)

    def ell(self, cx, cy, d, fill, outline=None, width=None):
        r = d / 2.0
        w = self.lw if width is None else max(1, int(round(width * self.u)))
        self.dr.ellipse([self.p(cx - r), self.p(cy - r), self.p(cx + r), self.p(cy + r)], fill=fill, outline=outline,
                        width=w if outline else 0)

    def line(self, pts, fill, width=1.2):
        self.dr.line([(self.p(x), self.p(y)) for x, y in pts], fill=fill, width=max(1, int(round(width * self.u))))

    def poly(self, pts, fill, outline=None):
        self.dr.polygon([(self.p(x), self.p(y)) for x, y in pts], fill=fill, outline=outline)

    def knob(self, cx, cy, d, fill, line=None):
        """Drehknopf: Scheibe mit Zeiger."""
        self.ell(cx, cy, d, fill, outline=line or OUTLINE, width=0.8)
        mark = "#e8e8ea" if _dark(fill) else "#1a1a1a"
        self.line([(cx, cy), (cx - d * 0.18, cy - d * 0.34)], mark, width=max(0.8, d * 0.13))

    def foot(self, cx, cy, d=8):
        self.ell(cx, cy, d, FOOT, outline=FOOT_EDGE, width=0.9)
        self.ell(cx, cy, d * 0.45, "#9a9ba0")

    def texture(self, x0, y0, x1, y1, kind, base):
        """Bespannung: feine Linien in leicht dunklerer Farbe."""
        col = _shade(base, 0.82)
        if kind == "lines":
            y = y0 + 1.5
            while y < y1:
                self.line([(x0, y), (x1, y)], col, width=0.5)
                y += 2.2
        elif kind == "weave":
            # Diagonalen in beide Richtungen, auf das Rechteck beschnitten
            step = 3.0
            c = (y0 - x1) - step
            while c < y1 - x0:            # y - x = c
                xa, xb = max(x0, y0 - c), min(x1, y1 - c)
                if xb > xa:
                    self.line([(xa, xa + c), (xb, xb + c)], col, width=0.5)
                c += step
            c = (x0 + y0) - step
            while c < x1 + y1:            # y + x = c
                xa, xb = max(x0, c - y1), min(x1, c - y0)
                if xb > xa:
                    self.line([(xa, c - xa), (xb, c - xb)], col, width=0.5)
                c += step
        elif kind == "diamond":
            y = y0 + 1.5
            i = 0
            while y < y1:
                x = x0 + 1.5 + (1.5 if i % 2 else 0)
                while x < x1:
                    self.ell(x, y, 1.1, col)
                    x += 3.0
                y += 2.6
                i += 1


def _dark(col):
    r, g, b = int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16)
    return (r * 299 + g * 587 + b * 114) / 1000 < 110


def _shade(col, f):
    r, g, b = int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16)
    return "#%02x%02x%02x" % (max(0, min(255, int(r * f))), max(0, min(255, int(g * f))), max(0, min(255, int(b * f))))


def _knob_row(pen, x0, x1, cy, n, d, fill, line=None):
    if n <= 0:
        return
    span = x1 - x0
    for i in range(n):
        cx = x0 + span * (i + 0.5) / n
        pen.knob(cx, cy, d, fill, line)


def _head(pen, L):
    hgt = L.get("hgt", 44)
    y0 = 35 - hgt / 2.0
    y1 = 35 + hgt / 2.0
    body = L["body"]
    # Griff und Gehaeuse
    pen.rect(38, y0 - 5, 62, y0 + 1, "#2a2b30", r=2)
    pen.rect(4, y0, 96, y1, body, r=4, outline=OUTLINE, width=0.8)
    pos = L.get("panel_pos", "bottom")
    ph = L.get("panel_h", 15)
    ins = 3.5
    if pos == "mid":
        px0, py0, px1, py1 = 4 + ins, y0 + ins, 96 - ins, y1 - ins
        gz = None
    elif pos == "top":
        px0, py0, px1, py1 = 4 + ins, y0 + ins, 96 - ins, y0 + ins + ph
        gz = (4 + ins, py1 + 2.5, 96 - ins, y1 - ins)
    else:
        px0, py0, px1, py1 = 4 + ins, y1 - ins - ph, 96 - ins, y1 - ins
        gz = (4 + ins, y0 + ins, 96 - ins, py0 - 2.5)
    # Bespannung
    if gz and L.get("grille"):
        gx0, gy0, gx1, gy1 = gz
        pen.rect(gx0, gy0, gx1, gy1, L["grille"], r=1.5)
        if L.get("tex"):
            pen.texture(gx0 + 0.5, gy0 + 0.5, gx1 - 0.5, gy1 - 0.5, L["tex"], L["grille"])
        if L.get("logo"):
            lx = gx0 + 3 if pos == "bottom" else gx0 + 3
            pen.rect(lx, gy0 + 2.5, lx + 14, gy0 + 6.5, L["logo"], r=1.5)
    elif L.get("logo") and pos == "mid":
        pen.rect(px0 + 3, py1 - 6, px0 + 17, py1 - 2.5, L["logo"], r=1.5)
    elif L.get("logo") and gz:      # Gehaeusefarbe ohne Bespannung (Orange): Logo oben links
        pen.rect(gz[0] + 3, gz[1] + 2.5, gz[0] + 17, gz[1] + 6.5, L["logo"], r=1.5)
    # Bedienfeld
    pen.rect(px0, py0, px1, py1, L["panel"], r=1.5)
    n = L.get("knobs", 6)
    d = 6.5 if n <= 6 else (5.2 if n <= 8 else 4.2)
    ky = (py0 + py1) / 2.0 if pos != "mid" else (py0 + py1) / 2.0 + (2 if L.get("logo") else 0)
    if pos == "top" and L.get("panel_h", 15) > 18:
        ky = py0 + 7
    kx0 = px0 + (14 if L.get("tag") else 4)
    kx1 = px1 - (8 if L.get("led") else 4)
    _knob_row(pen, kx0, kx1, ky, n, d, L.get("knob", KNOB_BLK), L.get("knob_line"))
    if L.get("tag"):
        pen.rect(px0 + 2.5, ky - 2.5, px0 + 12, ky + 2.5, L["tag"], r=1)
    if L.get("led"):
        pen.ell(px1 - 4, ky, 2.6, L["led"])


def _nam(pen, L):
    """NAM-Block: Amp-Topteil (Bedienfeld unten: Model/Input/Output) mit einem kleinen
    neuronalen Netz auf der Bespannung - erkennbar als Amp und als NAM."""
    _head(pen, dict(L, tex=None, logo=None, panel_pos="bottom"))
    hgt = L.get("hgt", 44)
    y0 = 35 - hgt / 2.0 + 3.5
    y1 = 35 + hgt / 2.0 - 3.5 - L.get("panel_h", 15) - 2.5
    col, cy = L.get("net", "#35d0c0"), (y0 + y1) / 2.0
    layers = [(30, 3), (46, 4), (62, 4), (78, 2)]
    pts = [[(x, cy + (i - (n - 1) / 2.0) * 5.2) for i in range(n)] for x, n in layers]
    for a, b in zip(pts, pts[1:]):
        for p in a:
            for q in b:
                pen.line([p, q], "#1f6f69", width=0.45)
    for layer in pts:
        for x, y in layer:
            pen.ell(x, y, 2.6, col)
    pen.rect(10, cy - 2, 21, cy + 2, L.get("logo", col), r=1.5)   # Logo-Plakette links


def _cab(pen, L):
    w, h = L.get("w", 56), L.get("h", 60)
    x0, x1 = 50 - w / 2.0, 50 + w / 2.0
    y0, y1 = 35 - h / 2.0, 35 + h / 2.0
    body = L["body"]
    if L.get("slant"):
        # schraege Oberkante (Marshall-Slant): Oberseite schmaler
        pen.poly([(x0 + 4, y0), (x1 - 4, y0), (x1, y0 + 8), (x1, y1), (x0, y1), (x0, y0 + 8)], body, outline=OUTLINE)
        gy0 = y0 + 4
    else:
        pen.rect(x0, y0, x1, y1, body, r=3.5, outline=OUTLINE, width=0.8)
        gy0 = y0 + 3.5
    ins = 3.5
    if L.get("form") == "combo":
        ph = 11 if L.get("knobs") else 7
        pen.rect(x0 + ins, y0 + ins, x1 - ins, y0 + ins + ph, L.get("panel", body), r=1.5)
        n = L.get("knobs", 0)
        if n:
            d = 5 if n <= 6 else 3.8
            _knob_row(pen, x0 + ins + 2, x1 - ins - 2, y0 + ins + ph / 2.0, n, d, L.get("knob", KNOB_SLV))
        elif L.get("logo"):
            pen.rect(x0 + ins + 3, y0 + ins + 2, x0 + ins + 15, y0 + ins + 5, L["logo"], r=1)
        gy0 = y0 + ins + ph + 2.5
    gx0, gx1, gy1 = x0 + ins, x1 - ins, y1 - ins
    pen.rect(gx0, gy0, gx1, gy1, L["grille"], r=1.5)
    if L.get("tex"):
        pen.texture(gx0 + 0.5, gy0 + 0.5, gx1 - 0.5, gy1 - 0.5, L["tex"], L["grille"])
    # Lautsprecher
    n = L.get("spk", 1)
    cols = {0: 1, 1: 1, 2: 2, 4: 2, 8: 2}[n]
    rows = max(1, n // cols)
    gw, gh = gx1 - gx0, gy1 - gy0
    d = min(gw / cols, gh / rows) * 0.82
    ring = _shade(L["grille"], 0.6)
    for i in range(n):
        cx = gx0 + gw * ((i % cols) + 0.5) / cols
        cy = gy0 + gh * ((i // cols) + 0.5) / rows
        pen.ell(cx, cy, d, None, outline=ring, width=max(0.7, d * 0.07))
        pen.ell(cx, cy, d * 0.42, ring)
        pen.ell(cx, cy, d * 0.18, _shade(L["grille"], 0.75))
    if L.get("form") == "cab" and L.get("logo"):
        pen.rect(gx0 + 3, gy0 + 3, gx0 + 15, gy0 + 6.5, L["logo"], r=1)
    if L.get("tag"):
        pen.rect(gx1 - 12, gy1 - 7, gx1 - 3, gy1 - 3, L["tag"], r=1)
    if L.get("wave"):
        cy = (gy0 + gy1) / 2.0
        pts = []
        for i in range(21):
            x = gx0 + 4 + (gw - 8) * i / 20.0
            pts.append((x, cy + math.sin(i / 20.0 * math.pi * 3) * gh * 0.28 * (1 - abs(i - 10) / 12.0)))
        pen.line(pts, L["wave"], width=1.6)


def _pedal(pen, L):
    if L.get("wide"):
        x0, x1, y0, y1 = 20, 80, 10, 60
    elif L.get("big"):
        x0, x1, y0, y1 = 29, 71, 1, 69
    else:
        x0, x1, y0, y1 = 33, 67, 2, 68
    body = L["body"]
    pen.rect(x0, y0, x1, y1, body, r=4, outline=L.get("line", OUTLINE), width=0.8)
    if L.get("frame"):
        pen.rect(x0, y0, x0 + 3.5, y1, L["frame"], r=2)
        pen.rect(x1 - 3.5, y0, x1, y1, L["frame"], r=2)
    if L.get("band"):
        col, by0, by1 = L["band"]
        pen.rect(x0 + 3, by0, x1 - 3, by1, col, r=1.5)
    if L.get("led"):
        pen.ell((x0 + x1) / 2.0, y0 + 4.5, 2.8, L["led"])
    kn = str(L.get("knobs", "2"))
    kc, kl = L.get("knob", KNOB_BLK), L.get("knob_line")
    cx = (x0 + x1) / 2.0
    top = y0 + 12
    if kn == "1":
        pen.knob(cx, y0 + 18, 15, kc, kl)
    elif kn == "2":
        pen.knob(cx - 8, top, 10, kc, kl)
        pen.knob(cx + 8, top, 10, kc, kl)
    elif kn == "2s":
        pen.knob(cx - 7, y0 + 8, 6, kc, kl)
        pen.knob(cx + 7, y0 + 8, 6, kc, kl)
    elif kn == "2+1":
        pen.knob(cx - 8, top, 10, kc, kl)
        pen.knob(cx + 8, top, 10, kc, kl)
        pen.knob(cx, top + 14, 9, kc, kl)
    elif kn == "3":
        for dx in (-10, 0, 10):
            pen.knob(cx + dx, top, 8, kc, kl)
    elif kn == "3s":
        for dx in (-8, 0, 8):
            pen.knob(cx + dx, y0 + 14, 5, kc, kl)
    elif kn == "4":
        for dx in (-8, 8):
            pen.knob(cx + dx, top, 9, kc, kl)
            pen.knob(cx + dx, top + 13, 9, kc, kl)
    elif kn == "4s":
        for dx in (-9, -3, 3, 9):
            pen.knob(cx + dx, top, 5, kc, kl)
    elif kn == "6":
        for dx in (-13, 0, 13):
            pen.knob(cx + dx, y0 + 12, 9, kc, kl)
            pen.knob(cx + dx, y0 + 26, 9, kc, kl)
    if L.get("sliders"):
        n = L["sliders"]
        sx0, sx1 = x0 + 5, x1 - 5
        for i in range(n):
            sx = sx0 + (sx1 - sx0) * (i + 0.5) / n
            pen.line([(sx, y0 + 8), (sx, y0 + 30)], _shade(body, 0.6), width=0.8)
            cy = y0 + 12 + ((i * 7) % 15)
            pen.rect(sx - 1.6, cy - 1.2, sx + 1.6, cy + 1.2, KNOB_WHT)
    if L.get("sw"):
        pen.rect(cx - 1.2, y0 + 26, cx + 1.2, y0 + 32, "#8a8a8e", r=0.6)
    if L.get("boss"):
        pen.rect(x0 + 3, y1 - 26, x1 - 3, y1 - 3, L.get("plate", "#1b1b1e"), r=2.5)
        pen.rect(x0 + 7, y1 - 22, x1 - 7, y1 - 20, "#3a3b40", r=0.5)
    elif L.get("plate"):
        pen.rect(x0 + 3, y1 - 20, x1 - 3, y1 - 3, L["plate"], r=2)
        pen.foot(cx, y1 - 11)
    else:
        pen.foot(cx, y1 - 10)


def _round(pen, L):
    pen.ell(50, 35, 62, L["body"], outline=OUTLINE, width=0.8)
    # dunkler Keil unten (Fuzz-Face-"Laecheln")
    pen.dr.pieslice([pen.p(50 - 24), pen.p(35 - 24), pen.p(50 + 24), pen.p(35 + 24)], 30, 150, fill="#2a1a18")
    pen.knob(38, 22, 10, L.get("knob", KNOB_BLK))
    pen.knob(62, 22, 10, L.get("knob", KNOB_BLK))
    pen.foot(50, 46)


def _drop(pen, L):
    pts = [(26, 6), (74, 6), (77, 12), (60, 62), (50, 68), (40, 62), (23, 12)]
    pen.poly(pts, L["body"], outline=OUTLINE)
    deco = L.get("deco")
    if deco:
        if L.get("deco_kind") == "dots":
            for i in range(30):
                a = i * 2.39996
                r = 3 + 21 * (i / 30.0)
                x, y = 50 + math.cos(a) * r * 1.15, 30 + math.sin(a) * r * 0.9
                if abs(x - 50) < 24 - (y - 12) * 0.3 and 10 < y < 56:
                    pen.ell(x, y, 1.4, deco)
        else:
            for k in range(3):
                yb = 16 + k * 8
                pts2 = [(30 + i * 2, yb + math.sin(i / 20.0 * math.pi * 4) * 2.2) for i in range(21)]
                pen.line(pts2, deco, width=0.9)
    kc = "#2a2a2e"
    pen.knob(36, 26, 7, kc, "#8a8a8e")
    pen.knob(64, 26, 7, kc, "#8a8a8e")
    pen.knob(50, 40, 8, "#3f7fd9" if L.get("deco_kind") != "dots" else "#ee8a2a")
    pen.foot(50, 56, 7)


def _rack(pen, L):
    body = L["body"]
    pen.rect(2, 26, 98, 44, body, r=1.5, outline=OUTLINE, width=0.8)
    for x in (4, 94):   # Rackohren
        pen.rect(x, 28, x + 2, 42, _shade(body, 0.6))
    kx0 = 10
    if L.get("screen"):
        pen.rect(8, 30, 22, 40, L["screen"], r=1)
        kx0 = 26
    if L.get("buttons"):
        for i in range(L["buttons"]):
            pen.rect(30 + i * 9, 31.5, 36 + i * 9, 38.5, KNOB_WHT, r=1)
    n = L.get("knobs", 8)
    if n:
        d = 5.5 if n <= 6 else 4.4
        _knob_row(pen, kx0, 88 if L.get("led") else 92, 35, n, d, L.get("knob", KNOB_SLV))
    if L.get("led"):
        pen.ell(92, 35, 2.4, L["led"])


def _wah(pen, L):
    body = L["body"]
    frame = L.get("frame")
    if frame:
        pen.poly([(33, 3), (67, 3), (72, 68), (28, 68)], frame, outline=OUTLINE)
        pen.poly([(37, 4), (63, 4), (67, 67), (33, 67)], body)
    else:
        pen.poly([(34, 3), (66, 3), (71, 68), (29, 68)], body, outline=OUTLINE)
    if L.get("band"):
        pen.poly([(38, 7), (62, 7), (63, 14), (37, 14)], L["band"])
    # Gummiauflage mit Rillen
    pad = _shade(body, 0.7) if not _dark(body) else "#2b2c31"
    top = 17 if L.get("band") else 9
    pen.poly([(39, top), (61, top), (65, 63), (35, 63)], pad)
    y = top + 4
    while y < 61:
        w = 22 + (y - top) * 0.09
        pen.line([(50 - w / 2, y), (50 + w / 2, y)], _shade(pad, 0.7) if not _dark(pad) else "#3c3d43", width=0.7)
        y += 4.5


def _wham(pen, L):
    body = L["body"]
    pen.poly([(18, 3), (82, 3), (85, 68), (15, 68)], body, outline=OUTLINE)
    plate = L.get("plate", BLACK)
    pen.rect(32, 8, 60, 64, plate, r=3)
    pen.rect(38, 14, 54, 58, L.get("label", "#e8e8ea"), r=2)
    # Skala rechts, Regler unten rechts
    pen.rect(67, 10, 73, 52, "#1a1a1c", r=1)
    for i in range(7):
        pen.line([(68.5, 14 + i * 5.5), (71.5, 14 + i * 5.5)], "#8a8a8e", width=0.6)
    pen.knob(70, 59, 6, "#2a2a2e", "#8a8a8e")
    pen.ell(64, 60, 2.2, LED_RED)


def _jack(pen, L):
    # zwei Klinkenstecker (Send/Return)
    for cx, col in ((36, "#c9cacd"), (64, "#c9cacd")):
        pen.rect(cx - 2.5, 8, cx + 2.5, 34, col, r=1.2)
        pen.rect(cx - 5, 34, cx + 5, 62, "#3a3b41", r=3)
        pen.rect(cx - 1.2, 12, cx + 1.2, 16, "#1a1a1c")
    pen.line([(41, 46), (59, 46)], "#1fc9a1", width=1.4)


def _mix(pen, L):
    for i, lvl in enumerate((22, 40, 30)):
        x = 30 + i * 20
        pen.line([(x, 10), (x, 60)], "#4a4d56", width=1.6)
        pen.rect(x - 6, lvl - 3.5, x + 6, lvl + 3.5, "#c9cacd", r=1.5)
        pen.line([(x - 6, lvl), (x + 6, lvl)], "#1a1a1c", width=0.8)
