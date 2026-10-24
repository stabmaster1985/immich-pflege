"""Kommandozeile "pflege" – Standard ist immer die Vorschau."""

from __future__ import annotations

import csv
import json
import logging
import sys
from typing import Any, Callable, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import ConfigError, Settings
from .logsetup import setup_logging
from .rules import RuleError
from .service import CONFIRM_TRASH, ActionError, ImmichError, Pflege

app = typer.Typer(
    name="pflege",
    help="Wartungstool für Immich: Duplikate, Fotos ohne Ort, Massen-Tagging. "
         "Ohne Aktions-Schalter wird nur eine Vorschau angezeigt.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
out = Console()
err = Console(stderr=True)

# Für Tests austauschbar
service_factory: Callable[[], Pflege] = lambda: Pflege(Settings.from_env())  # noqa: E731

JsonOpt = typer.Option(False, "--json", help="Ausgabe als JSON")
CsvOpt = typer.Option(False, "--csv", help="Ausgabe als CSV")
NeuOpt = typer.Option(False, "--neu", help="Bibliothek vorher neu einlesen")


def _service() -> Pflege:
    try:
        svc = service_factory()
    except ConfigError as exc:
        err.print(f"[red]Konfiguration:[/red] {exc}")
        raise typer.Exit(2)
    setup_logging(svc.settings.log_file, stream=sys.stderr, stream_level=logging.WARNING)
    return svc


def _run(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except ImmichError as exc:
        err.print(f"[red]Immich:[/red] {exc}")
    except RuleError as exc:
        err.print("[red]Regeldatei fehlerhaft:[/red]")
        for e in exc.errors:
            err.print(f"  • {e}")
    except ActionError as exc:
        err.print(f"[red]Abgebrochen:[/red] {exc}")
    raise typer.Exit(1)


def _emit_json(data: Any) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _emit_csv(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]), extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: ("; ".join(map(str, v)) if isinstance(v, list) else v) for k, v in r.items()})


def _stand(svc: Pflege) -> None:
    lib = svc.library()
    err.print(f"[dim]Stand der Bibliothek: {lib.scanned_at} · {len(lib.assets)} Medien "
              f"(neu einlesen mit --neu)[/dim]")


def _yesno(v: bool) -> str:
    return "ja" if v else ""


# ------------------------------------------------------------------ version
@app.command()
def version(json_: bool = JsonOpt):
    """Tool- und Immich-Version anzeigen, API-Keys prüfen."""
    svc = _service()
    info = _run(svc.check_server)
    info = {"tool": __version__, "immich_url": svc.settings.immich_url, **info}
    if json_:
        _emit_json(info)
        return
    out.print(f"immich-pflege {__version__}")
    out.print(f"Immich: {svc.settings.immich_url} – "
              f"{'Version ' + info['version'] if info['version'] else '[red]nicht erreichbar[/red]'}")
    for name, k in info["schluessel"].items():
        mark = "[green]✓[/green]" if k["ok"] else "[red]✗[/red]"
        out.print(f"  {mark} {name}: {k.get('konto') or k.get('fehler')}")
    for w in info["warnungen"]:
        out.print(f"[yellow]Warnung:[/yellow] {w}")
    if not all(k["ok"] for k in info["schluessel"].values()):
        raise typer.Exit(1)


@app.command()
def einlesen(json_: bool = JsonOpt):
    """Bibliothek aller Benutzer neu einlesen und zwischenspeichern."""
    svc = _service()
    with err.status("Lese Bibliothek ein …"):
        lib = _run(svc.scan)
    counts = lib.counts()
    if json_:
        _emit_json({"stand": lib.scanned_at, "dauer_s": lib.duration_s, **counts})
        return
    out.print(f"{counts['gesamt']} Medien in {lib.duration_s:.1f} s eingelesen")
    for user, c in counts["benutzer"].items():
        out.print(f"  {user}: {c['gesamt']} ({c['upload']} Uploads, {c['extern']} extern)")
    for w in lib.warnings:
        out.print(f"[yellow]Warnung:[/yellow] {w}")


# ---------------------------------------------------------------- Duplikate
@app.command()
def duplikate(
    ins_album: bool = typer.Option(False, "--ins-album", help="Nicht behaltene Kopien ins Prüf-Album legen"),
    papierkorb: bool = typer.Option(False, "--papierkorb",
                                    help="Nicht behaltene Uploads in den Papierkorb (externe nie)"),
    ja: bool = typer.Option(False, "--ja", help="Rückfrage beim Papierkorb überspringen"),
    gruppe: Optional[list[str]] = typer.Option(None, "--gruppe", "-g", help="Nur diese Gruppe(n)"),
    behalten: Optional[list[str]] = typer.Option(
        None, "--behalten", help="Vorschlag überschreiben: GRUPPE=MEDIUM-ID (mehrfach möglich)"),
    erledigte: bool = typer.Option(False, "--erledigte", help="Auch erledigte Gruppen anzeigen"),
    neu: bool = NeuOpt, json_: bool = JsonOpt, csv_: bool = CsvOpt,
):
    """Duplikate finden (Immich + Prüfsumme + Dateiname/Zeit) und Behalten-Vorschlag zeigen."""
    if ins_album and papierkorb:
        err.print("[red]Bitte nur eine Aktion: --ins-album oder --papierkorb[/red]")
        raise typer.Exit(2)
    svc = _service()
    if neu:
        with err.status("Lese Bibliothek ein …"):
            _run(svc.scan)
    action = "album" if ins_album else "papierkorb" if papierkorb else None

    overrides: dict[str, str] = {}
    for item in behalten or []:
        if "=" not in item:
            err.print(f"[red]--behalten erwartet GRUPPE=MEDIUM-ID, nicht {item!r}[/red]")
            raise typer.Exit(2)
        g, a = item.split("=", 1)
        overrides[g.strip()] = a.strip()

    if action is None:
        view = _run(lambda: svc.duplicates_view(limit=0, include_done=erledigte or bool(gruppe)))
        groups = [g for g in view["gruppen"] if not gruppe or g["id"] in gruppe]
        for g in groups:
            if g["id"] in overrides:
                g["behalten"] = overrides[g["id"]]
        if json_:
            _emit_json({**view, "gruppen": groups})
            return
        if csv_:
            _emit_csv([{"gruppe": g["id"], "behalten": m["id"] == g["behalten"], "quellen": g["quellen"],
                        **{k: m[k] for k in ("id", "benutzer", "dateiname", "aufnahme", "extern",
                                             "favorit", "im_album", "gps", "breite", "hoehe", "punkte")},
                        "gruende": m["gruende"], "pfad": m["pfad"]}
                       for g in groups for m in g["medien"]])
            return
        _stand(svc)
        _print_groups(groups)
        out.print(f"\n{view['offen']} offene Gruppen ({view['benutzeruebergreifend']} benutzerübergreifend). "
                  "Aktionen: --ins-album oder --papierkorb")
        return

    groups_sel = None
    all_groups = not gruppe
    if gruppe:
        groups_sel = [{"id": g, "keep": overrides.get(g)} for g in gruppe]
    elif overrides:
        view = _run(lambda: svc.duplicates_view(limit=0, include_done=False))
        groups_sel = [{"id": g["id"], "keep": overrides.get(g["id"])} for g in view["gruppen"]]
        all_groups = False
    plan = _run(lambda: svc.apply_duplicates(action, groups_sel, all_groups, dry_run=True))
    if not plan["schritte"]:
        out.print("Nichts zu tun.")
        return
    if not json_:
        _print_steps(plan["schritte"])
        out.print(f"\n{plan['gruppen']} Gruppen: {plan['papierkorb']} → Papierkorb, "
                  f"{plan['album']} → Album „{svc.settings.review_album}“, {plan['keine']} unverändert")
    confirm = None
    if action == "papierkorb" and plan["papierkorb"]:
        if not ja:
            if not sys.stdin.isatty():
                err.print("[red]Papierkorb ohne Terminal nur mit --ja[/red]")
                raise typer.Exit(1)
            if not typer.confirm(f"{plan['papierkorb']} Medien in den Papierkorb verschieben?"):
                err.print("Abgebrochen.")
                raise typer.Exit(1)
        confirm = CONFIRM_TRASH
    res = _run(lambda: svc.apply_duplicates(action, groups_sel, all_groups, confirm=confirm))
    if json_:
        _emit_json(res)
        return
    r = res["ergebnis"]
    out.print(f"[green]Erledigt:[/green] {r['papierkorb']} im Papierkorb, {r['album']} im Prüf-Album")
    for f in r["fehler"]:
        out.print(f"[yellow]Fehler bei {f['id']}: {f['fehler']}[/yellow]")


def _print_groups(groups: list[dict]) -> None:
    for g in groups:
        title = f"Gruppe {g['id']} · {', '.join(g['quellen'])}"
        if g["benutzeruebergreifend"]:
            title += " · benutzerübergreifend"
        if g["erledigt"]:
            title += " · erledigt"
        t = Table(title=title, title_justify="left", expand=False, show_lines=False)
        for col in ("", "Datei", "Benutzer", "Aufnahme", "Quelle", "Auflösung", "Punkte", "Gründe", "ID"):
            t.add_column(col, overflow="fold")
        for m in g["medien"]:
            keep = m["id"] == g["behalten"]
            t.add_row("★" if keep else "", m["dateiname"], m["benutzer"], m["aufnahme"] or "",
                      "extern" if m["extern"] else "Upload",
                      f"{m['breite'] or '?'}×{m['hoehe'] or '?'}", str(m["punkte"]),
                      ", ".join(m["gruende"]), m["id"], style="bold green" if keep else None)
        out.print(t)


def _print_steps(steps: list[dict]) -> None:
    t = Table(title="Geplante Änderungen", title_justify="left")
    for col in ("Aktion", "Datei", "Benutzer", "Grund", "ID"):
        t.add_column(col, overflow="fold")
    labels = {"papierkorb": "[red]Papierkorb[/red]", "album": "Prüf-Album", "keine": "[dim]–[/dim]"}
    for s in steps:
        t.add_row(labels[s["aktion"]], s["dateiname"], s["benutzer"], s["grund"], s["id"])
    out.print(t)


# ---------------------------------------------------------------- Ohne Ort
@app.command("ohne-ort")
def ohne_ort(
    ort_uebernehmen: bool = typer.Option(False, "--ort-uebernehmen",
                                         help="Vorgeschlagenen Ort für die Auswahl übernehmen"),
    stunden: Optional[float] = typer.Option(None, "--stunden", help="Zeitfenster ± Stunden (Standard aus .env)"),
    medium: Optional[list[str]] = typer.Option(None, "--id", help="Nur diese Medien-ID(s)"),
    datum: Optional[list[str]] = typer.Option(None, "--datum", help="Nur dieser Tag (JJJJ-MM-TT), mehrfach möglich"),
    nur_vorschlaege: bool = typer.Option(False, "--nur-vorschlaege", help="Nur Medien mit Vorschlag zeigen"),
    neu: bool = NeuOpt, json_: bool = JsonOpt, csv_: bool = CsvOpt,
):
    """Medien ohne GPS mit Ortsvorschlag vom zeitlich nächsten Foto anzeigen."""
    svc = _service()
    if neu:
        with err.status("Lese Bibliothek ein …"):
            _run(svc.scan)
    view = _run(lambda: svc.no_location_view(stunden, limit=0, only_suggestions=nur_vorschlaege or ort_uebernehmen))
    days = [d for d in view["tage"] if not datum or d["datum"] in datum]
    items = [m for d in days for m in d["medien"] if not medium or m["id"] in medium]

    if ort_uebernehmen:
        ids = [m["id"] for m in items if m["vorschlag"] and m["aenderbar"]]
        if not ids:
            out.print("Keine Medien mit Vorschlag in der Auswahl.")
            return
        res = _run(lambda: svc.apply_no_location(ids, stunden))
        if json_:
            _emit_json(res)
            return
        out.print(f"[green]Ort für {res['aktualisiert']} Medien übernommen.[/green]")
        for s in res["uebersprungen"]:
            out.print(f"[yellow]Übersprungen {s['id']}: {s['grund']}[/yellow]")
        return

    if json_:
        _emit_json({**view, "tage": [{**d, "medien": [m for m in d["medien"] if m in items]} for d in days]})
        return
    if csv_:
        rows = []
        for m in items:
            v = m["vorschlag"] or {}
            rows.append({"id": m["id"], "datum": (m["aufnahme"] or "")[:10], "aufnahme": m["aufnahme"],
                         "dateiname": m["dateiname"], "benutzer": m["benutzer"], "extern": m["extern"],
                         "aenderbar": m["aenderbar"], "vorschlag_ort": v.get("ort"),
                         "breite": v.get("breite"), "laenge": v.get("laenge"),
                         "abstand_min": v.get("abstand_min"), "quelle_id": v.get("quelle_id")})
        _emit_csv(rows)
        return
    _stand(svc)
    t = Table(title=f"Medien ohne Ort (Fenster ±{view['max_stunden']:g} h)", title_justify="left")
    for col in ("Datum", "Zeit", "Datei", "Benutzer", "Vorschlag", "Abstand", "ID"):
        t.add_column(col, overflow="fold")
    for m in items:
        v = m["vorschlag"]
        sug = (v["ort"] or f"{v['breite']:.4f}, {v['laenge']:.4f}") if v else "[dim]–[/dim]"
        if v and not m["aenderbar"]:
            sug += " [dim](extern, gesperrt)[/dim]"
        aufnahme = m["aufnahme"] or ""
        t.add_row(aufnahme[:10], aufnahme[11:16], m["dateiname"], m["benutzer"], sug,
                  v["abstand_text"] if v else "", m["id"])
    out.print(t)
    out.print(f"\n{len(items)} Medien ohne Ort, {sum(1 for m in items if m['vorschlag'] and m['aenderbar'])} "
              "mit übernehmbarem Vorschlag. Übernehmen: --ort-uebernehmen (ggf. mit --datum/--id)")


# --------------------------------------------------------------------- Tags
@app.command()
def tags(
    anwenden: bool = typer.Option(False, "--anwenden", help="Fehlende Tags tatsächlich setzen"),
    regel: Optional[list[str]] = typer.Option(None, "--regel", "-r", help="Nur diese Regel(n) (Name)"),
    neu: bool = NeuOpt, json_: bool = JsonOpt, csv_: bool = CsvOpt,
):
    """Massen-Tagging nach /config/regeln.yaml (nur ergänzen, nie entfernen)."""
    svc = _service()
    if neu:
        with err.status("Lese Bibliothek ein …"):
            _run(svc.scan)
    if anwenden:
        res = _run(lambda: svc.tags_apply(regel))
        if json_:
            _emit_json(res)
            return
        for r in res["regeln"]:
            if "uebersprungen" in r:
                out.print(f"[dim]{r['name']}: übersprungen ({r['uebersprungen']})[/dim]")
            else:
                out.print(f"{r['name']}: {r['getaggt']} Medien getaggt ({', '.join(r['tags'])})")
        for w in res["warnungen"]:
            out.print(f"[yellow]Warnung:[/yellow] {w}")
        out.print(f"[green]Insgesamt {res['getaggt']} Medien getaggt.[/green]")
        return

    view = _run(lambda: svc.tags_preview(regel))
    if json_:
        _emit_json(view)
        return
    if csv_:
        _emit_csv([{"regel": r["name"], "tags": r["tags"], "aktiv": r["aktiv"], "treffer": r.get("treffer"),
                    "schon_getaggt": r.get("schon_getaggt"), "neu": r.get("neu")} for r in view["regeln"]])
        return
    _stand(svc)
    t = Table(title=f"Regeln aus {view['regeldatei']}", title_justify="left")
    for col in ("Regel", "Tags", "Treffer", "schon getaggt", "neu", "pro Benutzer"):
        t.add_column(col, overflow="fold")
    for r in view["regeln"]:
        if not r["aktiv"]:
            t.add_row(r["name"], ", ".join(r["tags"]), "[dim]inaktiv[/dim]", "", "", "", style="dim")
            continue
        per_user = ", ".join(f"{u}: {c['neu']}/{c['treffer']}" for u, c in r["benutzer"].items())
        t.add_row(r["name"], ", ".join(r["tags"]), str(r["treffer"]), str(r["schon_getaggt"]),
                  f"[bold]{r['neu']}[/bold]", per_user)
    out.print(t)
    for w in view["warnungen"]:
        out.print(f"[yellow]Warnung:[/yellow] {w}")
    out.print("\nAnwenden mit --anwenden (optional --regel NAME)")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
