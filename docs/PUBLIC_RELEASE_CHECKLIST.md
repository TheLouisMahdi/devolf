# Public release checklist

## Publication policy

The DEVolf repository is intended to be public. All files in its clean tracked
tree are approved for public read access. BeachEye is the only private component:
its source, history, source patches, caches, and generated DLLs must never be
committed or attached to a public DEVolf release.

Public DEVolf users may clone and inspect the application. Building the native
application requires a GitHub account with read access to the original private
BeachEye repository. The PowerShell build uses GitHub CLI to download the pinned
private commit directly at build time.

## Completed

- `TheLouisMahdi/devolf` was created with a new single-root history containing
  only the audited DEVolf snapshot.
- The tracked BeachEye mirror, compiled DLL, private source excerpts, in-tree
  cache, and older contaminated Git history were not transferred.
- The root commit uses the GitHub `noreply` identity rather than a personal email.
- `resolve-beacheye-source.ps1` requires GitHub CLI authentication and confirms
  that the configured dependency repository is private.
- The selected `ver_50_remaster` dependency is pinned by full commit SHA and
  serves every reported device build; an INFO build number does not change
  the source repository branch.
- Private source is cloned outside the public repository under
  `%LOCALAPPDATA%\DEVolf\BeachEye` by default.
- The build fails closed when the user lacks access, the repository is public,
  a commit cannot be verified, or the expected source layout is incomplete.
- Generated native DLLs, executables, build directories, sessions, and caches
  are ignored by Git.
- The current tracked tree passed pattern-based checks for private keys, GitHub
  tokens, AWS access keys, private BeachEye source paths, and native binaries.

## Before changing visibility

1. Confirm that the default branch is `release` and contains only one root
   commit.
2. Confirm that the repository has no other branches, tags, releases, packages,
   Actions artifacts, issue attachments, deploy keys, webhooks, or secrets that
   could expose BeachEye.
3. Run a final secret scan against every reachable object in the new repository.
4. Verify that an unauthorized GitHub account can clone DEVolf but receives a
   clear access failure when the resolver requests BeachEye.
5. Verify that an authorized account can run the documented build and receives
   the exact pinned BeachEye revisions through GitHub CLI.
6. Choose a public license if reuse and redistribution should be granted. Without
   a `LICENSE` file, publishing the source provides read access but does not grant
   an open-source license.

The original `wolfeye-v2` repository must remain private because its historical
objects contain earlier BeachEye source and DLLs. Only the clean `devolf`
repository is a candidate for public visibility.
