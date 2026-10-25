from pathlib import Path

import pytest

from immich_pflege.library import scan_library
from immich_pflege.rules import (Resolver, RuleError, apply, example_rules, load_rules, parse_rules, preview,
                                 read_rules_raw, save_rules)

from .helpers import asset, library

EXT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EXAMPLE = Path(__file__).parent.parent / "immich_pflege" / "regeln.example.yaml"


def errors_of(text, users=("frank", "julia")):
    with pytest.raises(RuleError) as exc:
        parse_rules(text, list(users))
    return exc.value.errors


def test_example_file_is_valid():
    rules = load_rules(EXAMPLE, ["frank", "julia"])
    assert len(rules) == 7
    assert rules[0].tags == ["Reisen/Italien/2024"]
    assert rules[1].land == ["italien"]
    assert not rules[5].aktiv and rules[5].benutzer == ["julia"]


def test_yaml_syntax_error_has_line():
    errs = errors_of("regeln:\n  - name: x\n    tag: [a\n")
    assert "YAML-Syntaxfehler" in errs[0] and "Zeile" in errs[0]


def test_readable_rule_errors():
    errs = errors_of("""
regeln:
  - name: Kaputt
    tag: A/B
    hersteler: Sony
    von: 2024-13-01
    bibliothek: irgendwo
    dateiname: '(['
  - name: Ohne Tag
    typ: foto
  - name: Ohne Bedingung
    tag: X
  - name: Kaputt
    tag: Y
    typ: foto
    benutzer: otto
""")
    text = "\n".join(errs)
    assert "Regel 1 „Kaputt“ (Zeile 3): unbekannter Schlüssel 'hersteler' – meintest du 'hersteller'?" in text
    assert "JJJJ-MM-TT" in text
    assert "'bibliothek' muss 'extern' oder 'upload' sein" in text
    assert "kein gültiger regulärer Ausdruck" in text
    assert "Regel 2 „Ohne Tag“ (Zeile 9): es fehlt 'tag'" in text
    assert "mindestens eine Bedingung" in text
    assert "doppelt vergeben" in text
    assert "unbekannte(r) Benutzer otto" in text


def test_missing_top_key_and_file(tmp_path):
    assert "regeln:" in errors_of("foo: 1")[0]
    assert load_rules(tmp_path / "fehlt.yaml") == []


def test_nested_tag_names_normalized():
    rules = parse_rules("regeln:\n  - tag: ' Reisen / Italien /'\n    typ: foto\n")
    assert rules[0].tags == ["Reisen/Italien"] and rules[0].name == "Regel 1"


def test_local_conditions_are_anded():
    r = parse_rules("""
regeln:
  - tag: T
    pfad: '/urlaub/'
    dateiname: '\\.jpg$'
    von: 2024-07-01
    bis: 2024-07-31
    hersteller: sony
    modell: '^ILCE'
    bibliothek: extern
    typ: foto
""")[0]
    ok = asset(name="DSC1.JPG", path="/mnt/Urlaub/DSC1.JPG", local="2024-07-31T23:59:00Z",
               make="SONY", model="ILCE-7M4", library_id=EXT)
    assert r.matches_local(ok)
    for change in (dict(path="/mnt/x/DSC1.JPG"), dict(file_name="DSC1.HEIC"),
                   dict(local_date_time="2024-08-01T00:00:00Z"), dict(make="Canon"),
                   dict(model="A7"), dict(library_id=None), dict(type="VIDEO")):
        data = ok.to_dict() | change
        from immich_pflege.models import Asset
        assert not r.matches_local(Asset(**data)), change


def test_preview_and_apply_against_mock(state, clients):
    # Julias Asset ist schon getaggt, Personen- und Albumbedingung per API
    lib = scan_library(clients, "Duplikat-Prüfung")
    julia_img = next(a for a in state.assets.values() if a["originalFileName"] == "IMG_0300.HEIC")
    tag = state.upsert_tag(state.user_id("julia"), "Reisen/Italien/2024")
    julia_img["_tags"].add(tag["id"])

    rules = parse_rules("""
regeln:
  - name: Italien
    tag: Reisen/Italien/2024
    von: 2024-07-10
    bis: 2024-07-25
  - name: Sony extern
    tags: [Kamera/Sony, Quelle/Extern]
    hersteller: SONY
    bibliothek: extern
    benutzer: frank
  - name: Album
    tag: Album/Italien
    album: Italien 2024
  - name: Aus
    tag: X
    typ: video
    aktiv: false
""", ["frank", "julia"])
    resolver = Resolver(clients)
    prev = {p["name"]: p for p in preview(rules, lib, resolver)}
    it = prev["Italien"]
    in_range = [a for a in lib.assets.values() if "2024-07-10" <= a.local_date_time[:10] <= "2024-07-25"]
    assert it["treffer"] == len(in_range)
    assert it["schon_getaggt"] == 1 and it["neu"] == len(in_range) - 1
    assert prev["Sony extern"]["treffer"] == 2 and prev["Sony extern"]["benutzer"] == {"frank": {"treffer": 2, "neu": 2}}
    assert prev["Album"]["treffer"] == 1
    assert "treffer" not in prev["Aus"]
    # Franks Album sieht Julia nicht – es wird trotzdem gefunden (über Franks Zugang, alle Besitzer)
    assert not any("Italien 2024" in w for w in resolver.warnings)
    r2 = Resolver(clients)
    assert r2.album_assets("julia", "Gibts nicht") == set() and any("nicht gefunden" in w for w in r2.warnings)

    calls_before = len(state.calls)
    res = {r["name"]: r for r in apply(rules, lib, Resolver(clients))}
    assert res["Italien"]["getaggt"] == len(in_range) - 1
    assert res["Sony extern"]["getaggt"] == 2
    assert res["Aus"]["uebersprungen"] == "inaktiv"
    assert not any(c[0] == "DELETE" and "tags" in c[1] for c in state.calls[calls_before:])

    frank = state.user_id("frank")
    values = {t["value"] for t in state.tags.values() if t["ownerId"] == frank}
    assert {"Kamera", "Kamera/Sony", "Quelle/Extern", "Reisen/Italien/2024"} <= values

    # Zweiter Lauf: nichts mehr neu
    again = preview(rules, lib, Resolver(clients))
    assert all(p.get("neu", 0) == 0 for p in again)
    assert julia_img["_tags"] == {tag["id"]}  # nichts entfernt, nichts doppelt


def test_editor_roundtrip(tmp_path):
    path = tmp_path / "regeln.yaml"
    items = [
        {"name": "Italien", "tags": ["Reisen/Italien"], "von": "2024-07-01", "bis": "", "album": [],
         "benutzer": ["frank"], "aktiv": True, "pfad": None},
        {"name": "Zwei", "tags": ["A", "B/C"], "typ": "video", "aktiv": False, "person": ["Oma", "Opa"]},
    ]
    rules = save_rules(path, items=items, known_users=["frank", "julia"])
    assert [r.name for r in rules] == ["Italien", "Zwei"]
    text, back, errors = read_rules_raw(path)
    assert errors == []
    assert back[0] == {"name": "Italien", "tag": "Reisen/Italien", "von": "2024-07-01", "benutzer": "frank"}
    assert back[1] == {"name": "Zwei", "tags": ["A", "B/C"], "person": ["Oma", "Opa"], "typ": "video",
                       "aktiv": False}
    assert text.startswith("# Regeln")


def test_save_rejects_broken_and_keeps_file(tmp_path):
    path = tmp_path / "regeln.yaml"
    save_rules(path, items=[{"name": "ok", "tag": "X", "typ": "foto"}])
    before = path.read_text()
    with pytest.raises(RuleError):
        save_rules(path, items=[{"name": "kaputt", "tag": "X", "typ": "bild"}])
    with pytest.raises(RuleError):
        save_rules(path, text="regeln: [")
    assert path.read_text() == before
    text, items, errors = read_rules_raw(path)
    assert items and not errors


def test_example_rules_are_inactive():
    ex = example_rules()
    assert len(ex) == 7 and all(r["aktiv"] is False for r in ex)


def test_place_conditions(state, clients):
    lib = scan_library(clients, "Duplikat-Prüfung")
    rules = parse_rules("regeln:\n  - name: Italien\n    tag: Reisen/Italien\n    land: ITALIEN\n"
                            "  - name: Siena\n    tag: Orte/Siena\n    ort: [Siena, Florenz]\n    region: Toskana\n", ["frank", "julia"])
    res = {r["name"]: r for r in preview(rules, lib, Resolver(clients))}
    with_country = sum(1 for a in lib.assets.values() if a.country == "Italien")
    assert res["Italien"]["treffer"] == with_country > 0
    assert res["Siena"]["treffer"] == sum(1 for a in lib.assets.values() if a.city in ("Siena", "Florenz"))
