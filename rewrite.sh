git filter-branch -f --env-filter '
if [ "$GIT_AUTHOR_EMAIL" = "ai@assistant.com" ]; then
    export GIT_AUTHOR_NAME="Avigyan Das"
    export GIT_AUTHOR_EMAIL="avigyandas941@gmail.com"
    export GIT_COMMITTER_NAME="Avigyan Das"
    export GIT_COMMITTER_EMAIL="avigyandas941@gmail.com"
fi
' -- --all
