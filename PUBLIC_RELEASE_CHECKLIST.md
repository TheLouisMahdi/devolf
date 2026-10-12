# Public release checklist

Do not change this repository to public visibility until every blocking item
below has been resolved. Removing a file in the latest commit does not remove it
from Git history.

## Completed for the current tree

- The tracked BeachEye source mirror has been removed.
- Generated BeachEye DLLs have been removed and are ignored by Git.
- Source patches containing excerpts from the private dependency have been
  replaced by a narrow cache-only compatibility transformation.
- The resolver requires GitHub CLI authentication, verifies that the dependency
  repository is private, pins full commit SHAs, and stores the checkout outside
  the public repository.
- The repository-local private source cache and the personal VS Code path have
  been removed.
- A pattern-based scan of the current tracked text files found no private keys,
  GitHub tokens, AWS access keys, or obvious embedded credentials. This is not a
  substitute for a dedicated secret scanner.

## Blocking before publication

1. **Create a clean public history or rewrite the existing history.** Earlier
   commits contain BeachEye headers, implementation files, source snapshots,
   patches, and compiled DLLs under several paths, including
   `code/native/COMPATIBLE`, `code/native/beacheye`, `code/native/original`, and
   the older nested `wolfeye` tree. A normal deletion commit does not protect
   those objects after the repository becomes public.
2. **Choose a repository license.** No top-level `LICENSE` file currently
   grants redistribution rights. Confirm ownership and the intended public
   license before adding one.
3. **Confirm redistribution permission for non-BeachEye company material.** In
   particular, review `code/native/DataProvider`, the FC22 inspection PDF
   templates, company/product logos and icons, fault-scenario files, protocol
   constants, and company-derived TCC behavior.
4. **Review contributor privacy.** Existing history exposes contributor names
   and email addresses. Decide whether the clean public history should preserve
   or replace that metadata.
5. **Scan the final rewritten history.** Run a dedicated scanner such as
   Gitleaks against all branches and tags after the history cleanup, then inspect
   large and binary Git objects manually.
6. **Review GitHub metadata and settings.** Check repository description,
   topics, branch protection, Actions secrets, deploy keys, webhooks, releases,
   issue attachments, and every branch/tag before changing visibility.

## Recommended publication path

The lowest-risk option is a new public repository created from the audited
current snapshot, with a reviewed license and only approved assets. If the
existing repository URL must be retained, use a coordinated history rewrite,
force-push every retained branch and tag, remove stale refs/releases, and have
all collaborators reclone. Keep the repository private until that operation is
complete and independently verified.
