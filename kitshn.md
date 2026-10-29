# kitshn

This repository deploys with [kitshn 2](https://kit.yarden-zamir.com).

- `kitshn.config.ts` names the app and its deploys: a Compose app on a machine labelled `docker`, open to everyone, because the app has its own GitHub login.
- `.github/workflows/kitshn.yml` calls `kitshn2-deploy.yml`. It signs in to kitshn with GitHub OIDC, so the repo needs no deploy secrets.
- A push to `main` deploys `prod` at `money.yarden-zamir.com`. Each pull request deploys a `pr-<number>` preview at `money-pr-<number>.yarden-zamir.com`, and kitshn removes it when the pull request closes.
- GitHub secrets and variables named `KITSHN_<NAME>` reach the app as `<NAME>`.

## This app

- Services: `app`, and `cache` (Redis with no persistence). `${KITSHN_DATA_DIR}/state` is mounted at `/data`. It holds only caches of GitHub state, so losing it costs a re-clone and a sign-in, not budget history.
- Required params: `KITSHN_GITHUB_CLIENT_ID`, `KITSHN_GITHUB_CLIENT_SECRET`, `KITSHN_SESSION_SECRET`, `KITSHN_TOKEN_ENCRYPTION_KEY`, `KITSHN_BASE_URL`.
- Optional params: `KITSHN_DEFAULT_DATA_REPO`, `KITSHN_GOOGLE_CLOUD_API_KEY`.
- `specs/deployment.md` has the details.
