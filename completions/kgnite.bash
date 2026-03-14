_kgnite_completions() {
  local cur prev words cword
  _init_completion || return

  local commands="usage doctor search info files download pull-notebook submit leaderboard submissions upload-dataset upload-model browse"
  local resources_plural="datasets competitions kernels models"
  local resources_singular="dataset competition notebook model"
  local download_resources="dataset competition model notebook-output"
  local model_actions="create update"

  if [[ $cword -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
    return
  fi

  case "${words[1]}" in
    search)
      if [[ $cword -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "$resources_plural" -- "$cur") )
        return
      fi
      case "$prev" in
        --sort-by)
          case "${words[2]}" in
            datasets) COMPREPLY=( $(compgen -W "hottest votes updated active" -- "$cur") ) ;;
            competitions) COMPREPLY=( $(compgen -W "grouped prize earliestDeadline latestDeadline numberOfTeams recentlyCreated" -- "$cur") ) ;;
            kernels) COMPREPLY=( $(compgen -W "hotness commentCount dateCreated dateRun relevance scoreAscending scoreDescending viewCount voteCount" -- "$cur") ) ;;
            models) COMPREPLY=( $(compgen -W "hotness downloadCount voteCount notebookCount createTime" -- "$cur") ) ;;
          esac
          return
          ;;
        --category)
          COMPREPLY=( $(compgen -W "all featured research recruitment gettingStarted masters playground" -- "$cur") )
          return
          ;;
        --group)
          COMPREPLY=( $(compgen -W "general entered inClass" -- "$cur") )
          return
          ;;
        --language)
          COMPREPLY=( $(compgen -W "all python r sqlite julia" -- "$cur") )
          return
          ;;
        --kernel-type)
          COMPREPLY=( $(compgen -W "all script notebook" -- "$cur") )
          return
          ;;
        --output-type)
          COMPREPLY=( $(compgen -W "all visualizations data" -- "$cur") )
          return
          ;;
      esac
      COMPREPLY=( $(compgen -W "--sort-by --page --page-size --owner --user --category --group --language --kernel-type --output-type --dataset --competition --json" -- "$cur") )
      ;;
    info)
      if [[ $cword -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "$resources_singular" -- "$cur") )
        return
      fi
      COMPREPLY=( $(compgen -W "--json" -- "$cur") )
      ;;
    files)
      if [[ $cword -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "$resources_singular" -- "$cur") )
        return
      fi
      COMPREPLY=( $(compgen -W "--page-size --page-token --json" -- "$cur") )
      ;;
    download)
      if [[ $cword -eq 2 ]]; then
        COMPREPLY=( $(compgen -W "$download_resources" -- "$cur") )
        return
      fi
      COMPREPLY=( $(compgen -W "--path --output-dir --force --json" -- "$cur") )
      ;;
    pull-notebook)
      COMPREPLY=( $(compgen -W "--output-dir --json" -- "$cur") )
      ;;
    submit)
      COMPREPLY=( $(compgen -W "--file --kernel --version --message --json" -- "$cur") )
      ;;
    leaderboard)
      COMPREPLY=( $(compgen -W "--show --download --output-dir --page-size --page-token --json" -- "$cur") )
      ;;
    submissions)
      COMPREPLY=( $(compgen -W "--json" -- "$cur") )
      ;;
    upload-dataset)
      COMPREPLY=( $(compgen -W "--handle --message --ignore --version --public --keep-tabular --dir-mode --delete-old-versions --json" -- "$cur") )
      ;;
    upload-model)
      if [[ "$prev" == "--action" ]]; then
        COMPREPLY=( $(compgen -W "$model_actions" -- "$cur") )
        return
      fi
      COMPREPLY=( $(compgen -W "--handle --message --license-name --ignore --sigstore --action --json" -- "$cur") )
      ;;
    browse)
      if [[ "$prev" == "--resource" ]]; then
        COMPREPLY=( $(compgen -W "$resources_plural" -- "$cur") )
        return
      fi
      COMPREPLY=( $(compgen -W "--resource --search --sort-by --page --page-size --limit --output-dir" -- "$cur") )
      ;;
  esac
}

complete -F _kgnite_completions kgnite
