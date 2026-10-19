# Keys

`catalog.pub` is the [minisign](https://jedisct1.github.io/minisign/) public
key of the catalog. OpenRig embeds it and refuses an index whose signature
does not match it.

The secret key is not here and never will be: the owner keeps it off the
repository and the CI, and signs each index by hand with
`tools/sign_index.sh` (see [docs/BUILDING.md](../docs/BUILDING.md)).

Changing the key means a new OpenRig release that embeds the new
`catalog.pub`: devices with the old one stop accepting the index.
