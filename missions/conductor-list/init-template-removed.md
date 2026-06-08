## `conductor init --template` Was Removed

`conductor init --template` was removed during the registry redesign.
Template-to-workflow instantiation currently has no CLI surface — templates must
be copied manually or via `shutil.copy2()`. The VAL-CROSS-006 cross-command
integration test simulates this step.

This is a known architectural gap. If `init --template` is restored in the
future, tests should be updated from `shutil.copy2()` to real `CliRunner.invoke`
of `init --template`.
