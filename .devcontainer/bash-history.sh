# Save before each prompt so closing a terminal cannot discard its history.
export HISTFILE=/commandhistory/.bash_history
HISTSIZE=10000
HISTFILESIZE=20000
shopt -s histappend
# Reread after saving: history -n can skip entries appended by another shell.
[[ ${PROMPT_COMMAND[*]} == *'history -a && history -c && history -r'* ]] ||
    PROMPT_COMMAND+=('history -a && history -c && history -r')
