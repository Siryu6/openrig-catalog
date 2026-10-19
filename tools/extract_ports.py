#!/usr/bin/env python3
"""Read the ports of an LV2 plugin from the Turtle files of its bundle.

    tools/extract_ports.py <plugin id> <bundle dir or .ttl file>...

Writes ports/<plugin id>.json: the audio and control ports, the features the
plugin requires and ports_hash, the fingerprint of its port contract (index,
symbol and type of every port). The URI comes from plugins/<plugin id>.yaml.

Run it on the bundle that is published, after it is built: some projects
(DPF, x42) generate their .ttl at build time.
"""

import hashlib
import json
import sys
from pathlib import Path

import yaml
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

LV2 = Namespace("http://lv2plug.in/ns/lv2core#")  # LV2["index"]: LV2.index is str.index
UNITS = Namespace("http://lv2plug.in/ns/extensions/units#")
PPROPS = Namespace("http://lv2plug.in/ns/ext/port-props#")
DOAP = Namespace("http://usefulinc.com/ns/doap#")

ROOT = Path(__file__).resolve().parent.parent

# Port properties the app cares about, by their short name
PROPERTIES = {
    LV2.toggled: "toggled",
    LV2.integer: "integer",
    LV2.enumeration: "enumeration",
    LV2.sampleRate: "sample_rate",
    PPROPS.logarithmic: "logarithmic",
    PPROPS.notOnGUI: "hidden",
    PPROPS.expensive: "expensive",
    LV2.connectionOptional: "optional",
}


def number(value):
    if value is None:
        return None
    n = float(value.toPython()) if isinstance(value, Literal) else float(value)
    return int(n) if n.is_integer() else round(n, 6)


def text(graph, subject, predicate):
    """English (or untagged) literal of subject/predicate"""
    values = [v for v in graph.objects(subject, predicate) if isinstance(v, Literal)]
    for v in values:
        if v.language in (None, "en"):
            return str(v)
    return str(values[0]) if values else None


def unit(graph, port):
    u = graph.value(port, UNITS.unit)
    if u is None:
        return None
    if isinstance(u, URIRef) and str(u).startswith(str(UNITS)):
        return str(u)[len(str(UNITS)):]
    return text(graph, u, UNITS.symbol) or text(graph, u, RDFS.label)


def port_kind(graph, port):
    types = set(graph.objects(port, RDF.type))
    direction = "in" if LV2.InputPort in types else "out" if LV2.OutputPort in types else "?"
    for t, name in ((LV2.AudioPort, "audio"), (LV2.ControlPort, "control"), (LV2.CVPort, "cv")):
        if t in types:
            return name, direction
    others = sorted(str(t).rsplit("#", 1)[-1] for t in types if t not in (LV2.InputPort, LV2.OutputPort))
    return (others[0] if others else "unknown"), direction


def extract(uri, sources):
    graph = Graph()
    for source in sources:
        files = sorted(source.glob("*.ttl")) if source.is_dir() else [source]
        for f in files:
            graph.parse(f, format="turtle")
    plugin = URIRef(uri)
    if (plugin, RDF.type, LV2.Plugin) not in graph:
        sys.exit(f"{uri}: not described in {', '.join(map(str, sources))}")

    ports = []
    for port in graph.objects(plugin, LV2.port):
        kind, direction = port_kind(graph, port)
        entry = {
            "index": int(graph.value(port, LV2["index"])),
            "symbol": str(graph.value(port, LV2.symbol)),
            "name": text(graph, port, LV2.name),
            "type": kind,
            "direction": direction,
        }
        if kind == "control" and direction == "in":
            entry["min"] = number(graph.value(port, LV2.minimum))
            entry["max"] = number(graph.value(port, LV2.maximum))
            entry["default"] = number(graph.value(port, LV2.default))
            entry["unit"] = unit(graph, port)
            props = sorted(PROPERTIES[p] for p in graph.objects(port, LV2.portProperty) if p in PROPERTIES)
            if props:
                entry["properties"] = props
            designation = graph.value(port, LV2.designation)
            if designation is not None:
                # lv2:enabled is the plugin's own bypass, not a control
                entry["designation"] = str(designation).rsplit("#", 1)[-1]
            points = sorted(
                ((number(graph.value(sp, RDF.value)), text(graph, sp, RDFS.label))
                 for sp in graph.objects(port, LV2.scalePoint)),
                key=lambda p: (p[0] is None, p[0]),
            )
            if points:
                entry["scale_points"] = [{"value": v, "label": l} for v, l in points]
        ports.append(entry)
    ports.sort(key=lambda p: p["index"])

    contract = "\n".join(f'{p["index"]} {p["symbol"]} {p["type"]} {p["direction"]}' for p in ports)
    minor = graph.value(plugin, LV2.minorVersion)
    micro = graph.value(plugin, LV2.microVersion)
    return {
        "uri": uri,
        "name": text(graph, plugin, DOAP.name),
        "version": f"{minor}.{micro}" if minor is not None and micro is not None else None,
        "license": str(graph.value(plugin, DOAP.license) or "") or None,
        "classes": sorted(
            str(t)[len(str(LV2)):] for t in graph.objects(plugin, RDF.type)
            if str(t).startswith(str(LV2)) and t != LV2.Plugin
        ),
        "required_features": sorted(str(f) for f in graph.objects(plugin, LV2.requiredFeature)),
        "audio": {
            "inputs": sum(p["type"] == "audio" and p["direction"] == "in" for p in ports),
            "outputs": sum(p["type"] == "audio" and p["direction"] == "out" for p in ports),
        },
        "ports_hash": hashlib.sha256(contract.encode()).hexdigest(),
        "ports": ports,
    }


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    plugin_id = sys.argv[1]
    meta = yaml.safe_load((ROOT / "plugins" / f"{plugin_id}.yaml").read_text())
    result = extract(meta["uri"], [Path(a) for a in sys.argv[2:]])
    out = ROOT / "ports" / f"{plugin_id}.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    controls = [p for p in result["ports"] if p["type"] == "control" and p["direction"] == "in"]
    print(f"{out.relative_to(ROOT)}: {len(controls)} controls, "
          f"{result['audio']['inputs']} in / {result['audio']['outputs']} out")


if __name__ == "__main__":
    main()
