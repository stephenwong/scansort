"""Shell completion generator CLI subcommand handler."""

import argparse

_BASH_TEMPLATE = """# Bash completion for scansort
_scansort_completion() {
    local cur prev opts subcommands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    subcommands="watch config undo rescan check-update logs history stats help completion"

    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "$subcommands --version -V --help -v --verbose --dry-run --minimized" -- "$cur") )
        return 0
    fi

    case "${COMP_WORDS[1]}" in
        watch)
            opts="--watch-folder --documents-root --dry-run --minimized -v --verbose --help"
            ;;
        config)
            opts="--show --json --path --get --set --set-key --watch-folder --documents-folder --autostart --gemini-model --fallback-folder --max-depth --mirror-csv --auto-update --update-check-interval --dry-run -v --verbose --help"
            ;;
        logs)
            opts="-n --lines -f --follow --level --clear -v --verbose --help"
            ;;
        history)
            opts="-n --limit --status -q --search --reverse --json -v --verbose --help"
            ;;
        stats)
            opts="--json -v --verbose --help"
            ;;
        rescan)
            opts="--json -v --verbose --help"
            ;;
        check-update)
            opts="--json -v --verbose --help"
            ;;
        help)
            opts="$subcommands"
            ;;
        completion)
            opts="bash zsh fish powershell"
            ;;
        *)
            opts="-v --verbose --help"
            ;;
    esac

    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
    return 0
}
complete -F _scansort_completion scansort
"""

_ZSH_TEMPLATE = """#compdef scansort

_scansort() {
    local -a commands
    commands=(
        'watch:Start background drop folder monitor'
        'config:Manage application settings and secrets'
        'undo:Reverse the last filed document move'
        'rescan:Rescan and display Documents folder taxonomy'
        'check-update:Check GitHub Releases for newer ScanSort versions'
        'logs:View, filter, or tail execution logs'
        'history:View and search document filing history'
        'stats:Display aggregate filing metrics and estimated cost'
        'help:Show help for a command'
        'completion:Generate shell completion script'
    )

    _arguments -C \\
        '(-V --version)'{-V,--version}'[Show version number]' \\
        '(-v --verbose)'{-v,--verbose}'[Enable verbose debug logging]' \\
        '--dry-run[Simulate actions without moving files]' \\
        '--minimized[Start minimized to tray]' \\
        '1: :->command' \\
        '*:: :->args'

    case $state in
        command)
            _describe -t commands 'scansort command' commands
            ;;
        args)
            case $line[1] in
                watch)
                    _arguments \\
                        '--watch-folder[Override drop folder]:directory:_files -/' \\
                        '--documents-root[Override documents root]:directory:_files -/' \\
                        '--dry-run[Simulate actions without moving files]' \\
                        '--minimized[Start minimized to tray]' \\
                        '(-v --verbose)'{-v,--verbose}'[Enable verbose debug logging]'
                    ;;
                config)
                    _arguments \\
                        '--show[Display current configuration]' \\
                        '--json[Output configuration as JSON]' \\
                        '--path[Print configuration file path]' \\
                        '--get[Inspect a setting]:key:' \\
                        '--set[Set a setting]:key: :val:' \\
                        '--set-key[Store Gemini API key]:key:' \\
                        '--watch-folder[Set drop folder]:directory:_files -/' \\
                        '--documents-folder[Set documents folder]:directory:_files -/' \\
                        '--gemini-model[Set default model]:model:(gemini-3.1-flash-lite gemini-3.5-flash-lite)' \\
                        '--fallback-folder[Set fallback review folder]:folder:' \\
                        '--max-depth[Set folder depth]:depth:' \\
                        '--mirror-csv[Toggle mirror CSV]:choice:(enable disable)' \\
                        '--auto-update[Toggle auto-updates]:choice:(enable disable)' \\
                        '--update-check-interval[Update check days]:days:' \\
                        '--dry-run[Toggle dry run]:choice:(enable disable)' \\
                        '--autostart[Toggle auto-start]:choice:(enable disable)'
                    ;;
                logs)
                    _arguments \\
                        '(-n --lines)'{-n,--lines}'[Lines to show]:count:' \\
                        '(-f --follow)'{-f,--follow}'[Follow log output]' \\
                        '--level[Filter level]:level:(DEBUG INFO WARNING ERROR CRITICAL)' \\
                        '--clear[Clear log file]'
                    ;;
                history)
                    _arguments \\
                        '(-n --limit)'{-n,--limit}'[Limit records]:count:' \\
                        '--status[Filter status]:status:(SUCCESS DUPLICATE FAILED UNDONE COLLISION_RENAMED)' \\
                        '(-q --search)'{-q,--search}'[Search query]:query:' \\
                        '--reverse[Oldest first]' \\
                        '--json[Output JSON]'
                    ;;
                stats)
                    _arguments '--json[Output JSON]'
                    ;;
                rescan|check-update)
                    _arguments '--json[Output JSON]'
                    ;;
                completion)
                    _arguments '1:shell:(bash zsh fish powershell)'
                    ;;
            esac
            ;;
    esac
}

_scansort "$@"
"""

_FISH_TEMPLATE = """# Fish completion for scansort
set -l commands watch config undo rescan check-update logs history stats help completion

complete -c scansort -f -n "not __fish_seen_subcommand_from $commands" -a "watch" -d "Start background drop folder monitor"
complete -c scansort -f -n "not __fish_seen_subcommand_from $commands" -a "config" -d "Manage application settings and secrets"
complete -c scansort -f -n "not __fish_seen_subcommand_from $commands" -a "undo" -d "Reverse the last filed document move"
complete -c scansort -f -n "not __fish_seen_subcommand_from $commands" -a "rescan" -d "Rescan and display Documents folder taxonomy"
complete -c scansort -f -n "not __fish_seen_subcommand_from $commands" -a "check-update" -d "Check GitHub Releases for newer versions"
complete -c scansort -f -n "not __fish_seen_subcommand_from $commands" -a "logs" -d "View, filter, or tail execution logs"
complete -c scansort -f -n "not __fish_seen_subcommand_from $commands" -a "history" -d "View and search document filing history"
complete -c scansort -f -n "not __fish_seen_subcommand_from $commands" -a "stats" -d "Display aggregate filing metrics and cost"
complete -c scansort -f -n "not __fish_seen_subcommand_from $commands" -a "help" -d "Show help for a command"
complete -c scansort -f -n "not __fish_seen_subcommand_from $commands" -a "completion" -d "Generate shell completion script"

complete -c scansort -l version -s V -d "Show program's version number"
complete -c scansort -l verbose -s v -d "Enable verbose debug logging"
complete -c scansort -l dry-run -d "Simulate actions without moving files"
complete -c scansort -l minimized -d "Start minimized to tray"

# Subcommand specific options
complete -c scansort -n "__fish_seen_subcommand_from watch" -l watch-folder -a "(__fish_complete_directories)" -d "Override drop folder"
complete -c scansort -n "__fish_seen_subcommand_from watch" -l documents-root -a "(__fish_complete_directories)" -d "Override documents root"
complete -c scansort -n "__fish_seen_subcommand_from watch" -l dry-run -d "Simulate actions"
complete -c scansort -n "__fish_seen_subcommand_from watch" -l minimized -d "Start minimized"

complete -c scansort -n "__fish_seen_subcommand_from config" -l show -d "Display current configuration"
complete -c scansort -n "__fish_seen_subcommand_from config" -l json -d "Output configuration as JSON"
complete -c scansort -n "__fish_seen_subcommand_from config" -l path -d "Print configuration path"
complete -c scansort -n "__fish_seen_subcommand_from config" -l get -d "Inspect a setting"
complete -c scansort -n "__fish_seen_subcommand_from config" -l set -d "Set a setting"
complete -c scansort -n "__fish_seen_subcommand_from config" -l set-key -d "Store Gemini API key"
complete -c scansort -n "__fish_seen_subcommand_from config" -l gemini-model -a "gemini-3.1-flash-lite gemini-3.5-flash-lite" -d "Set Gemini model"
complete -c scansort -n "__fish_seen_subcommand_from config" -l autostart -a "enable disable" -d "Toggle auto-start on boot"

complete -c scansort -n "__fish_seen_subcommand_from logs" -s n -l lines -d "Lines to show"
complete -c scansort -n "__fish_seen_subcommand_from logs" -s f -l follow -d "Follow log output"
complete -c scansort -n "__fish_seen_subcommand_from logs" -l level -a "DEBUG INFO WARNING ERROR CRITICAL" -d "Filter log level"
complete -c scansort -n "__fish_seen_subcommand_from logs" -l clear -d "Clear log file"

complete -c scansort -n "__fish_seen_subcommand_from history" -s n -l limit -d "Limit records"
complete -c scansort -n "__fish_seen_subcommand_from history" -l status -a "SUCCESS DUPLICATE FAILED UNDONE COLLISION_RENAMED" -d "Filter by status"
complete -c scansort -n "__fish_seen_subcommand_from history" -s q -l search -d "Search query"
complete -c scansort -n "__fish_seen_subcommand_from history" -l reverse -d "Reverse order"
complete -c scansort -n "__fish_seen_subcommand_from history" -l json -d "Output JSON"

complete -c scansort -n "__fish_seen_subcommand_from stats" -l json -d "Output JSON"
complete -c scansort -n "__fish_seen_subcommand_from rescan" -l json -d "Output JSON"
complete -c scansort -n "__fish_seen_subcommand_from check-update" -l json -d "Output JSON"
complete -c scansort -n "__fish_seen_subcommand_from completion" -a "bash zsh fish powershell" -d "Shell type"
"""

_POWERSHELL_TEMPLATE = """# PowerShell completion for scansort
Register-ArgumentCompleter -Native -CommandName scansort -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $subcommands = @('watch', 'config', 'undo', 'rescan', 'check-update', 'logs', 'history', 'stats', 'help', 'completion')
    $elements = $commandAst.ToString().Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)

    if ($elements.Count -le 1 -or ($elements.Count -eq 2 -and -not $wordToComplete.StartsWith('-'))) {
        $subcommands | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
            [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
        }
        return
    }

    $flags = @('--version', '-V', '--verbose', '-v', '--dry-run', '--minimized', '--help')
    if ($elements -contains 'watch') {
        $flags += @('--watch-folder', '--documents-root', '--dry-run', '--minimized')
    }
    elseif ($elements -contains 'config') {
        $flags += @('--show', '--json', '--path', '--get', '--set', '--set-key', '--watch-folder', '--documents-folder', '--gemini-model', '--fallback-folder', '--max-depth', '--mirror-csv', '--auto-update', '--update-check-interval', '--dry-run', '--autostart')
    }
    elseif ($elements -contains 'logs') {
        $flags += @('-n', '--lines', '-f', '--follow', '--level', '--clear')
    }
    elseif ($elements -contains 'history') {
        $flags += @('-n', '--limit', '--status', '-q', '--search', '--reverse', '--json')
    }
    elseif ($elements -contains 'stats' -or $elements -contains 'rescan' -or $elements -contains 'check-update') {
        $flags += @('--json')
    }

    $flags | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
        [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterName', $_)
    }
}
"""

_SHELL_TEMPLATES = {
    "bash": _BASH_TEMPLATE,
    "zsh": _ZSH_TEMPLATE,
    "fish": _FISH_TEMPLATE,
    "powershell": _POWERSHELL_TEMPLATE,
}


def handle_completion(parsed: argparse.Namespace) -> int:
    """Generate shell completion script for the requested shell."""
    shell = getattr(parsed, "shell", "bash").lower()
    template = _SHELL_TEMPLATES.get(shell)
    if not template:
        print(
            f"Unsupported shell: {shell}. Supported shells: bash, zsh, fish, powershell"
        )
        return 1
    print(template.strip())
    return 0
