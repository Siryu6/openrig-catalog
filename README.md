# OpenRig plugin catalog

The list of LV2 plugins that [OpenRig](https://github.com/Siryu6/OpenRig)
offers in its plugin store, and the tools that turn it into the index the
pedalboard downloads.

> Work in progress: OpenRig does not download this index yet. The store
> page in the app runs on a sample of it.

## What the store offers

Free and open-source plugins only, so that their sources can always be
published next to them. Each plugin:

- is downloaded **from its authors' own releases** when they publish a Linux
  build for the pedalboard's processor (`origin: upstream`). The index links
  to their file and pins its size and sha256, so a replaced file is refused;
- or, when they do not, is built by OpenRig from the pinned sources and
  published with those sources (`origin: openrig-build`);
- shows its license, its authors and, when the project has one, its own
  picture with credit (see [media/CREDITS.md](media/CREDITS.md)).

Plugins copied by hand into the pedalboard's LV2 folder keep working: the
store is one way in, not the only one.

## Layout

| Path | What |
|---|---|
| `families.yaml` | The families of the "Add effect" page and their subcategories |
| `packages/<id>.yaml` | One upstream project or release: version, license, source, artifacts per architecture |
| `plugins/<id>.yaml` | One plugin of a package: URI, bundle, family, texts, picture |
| `ports/<id>.json` | Its ports, read from the published bundle by `tools/extract_ports.py` |
| `media/` | Pictures taken from the projects' sources |
| `tools/build_index.py` | Checks everything and writes `dist/catalog-v1.json` |
| `tools/verify_artifacts.py` | Checks the pinned upstream files are unchanged (weekly in CI) |

## Adding a plugin

1. Add or update `packages/<package>.yaml`. For an upstream build, the
   artifact URLs come from the project's release page; compute size and
   sha256 from the downloaded file.
2. Write `plugins/<id>.yaml`. Texts are in English and our own words:
   `summary` is one line (80 characters at most), `description` two to four
   sentences. `inspired_by` names the classic gear the plugin models, as
   text only.
3. Read its ports from the bundle as published:

   ```sh
   pip install -r requirements.txt
   tools/extract_ports.py <id> path/to/Plugin.lv2
   ```

4. Optionally, a picture from the project's own repository in `media/`, with
   its `source` link at a fixed commit, credit and license. Never an image
   whose license is unclear.
5. Check: `tools/build_index.py --check`.

## The index

`tools/build_index.py` writes `dist/catalog-v1.json`: packages, their
artifacts, and for each plugin its texts, picture, audio inputs and outputs,
required LV2 features, control ports and `ports_hash` (the fingerprint of its
port layout, so an update that would break saved presets is caught). The
published index is signed; the signing key is not part of this repository.

## License

The tools and catalog texts are under the GPL-3.0 (see [LICENSE](LICENSE)).
Each picture keeps its project's license, listed in
[media/CREDITS.md](media/CREDITS.md). Product names in `inspired_by` belong
to their owners and only describe what a plugin models.
