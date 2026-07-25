#!/bin/sh
# ANK Shell Profile - injected into WS shell sessions
ANK_BIN="/data/local/ank/ankfs/opt/ank/bin"
[ -d "$ANK_BIN" ] && export PATH="$ANK_BIN:$PATH"
export PS1='\033[1;36mANK\033[0m:\033[1;33m\w\033[0m# '
