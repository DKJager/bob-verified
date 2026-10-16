# Third-party software

No code from any target application is included in this repository.

---

## IBM Bob (Bob Shell)

IBM Bob is the AI development tool used to write and operate parts of this project. It is used under IBM's terms of service. IBM Bob is not redistributed in this repository.

---

## simple_api

- **Author:** Max Mautner
- **Licence:** MIT (Copyright (c) 2014 Max Mautner)
- **Source:** https://github.com/mmautner/simple_api, commit `17067fe3113a746e0a5044af88f5777d6e50c999`
- **How used:** Fetched at run time by `scripts/fetch_target.sh` into a work directory outside this repository. Not distributed here.
- **Licence text:** Held in the upstream repository; not reproduced here.

---

## Libraries installed during the demo modernization

The following libraries are installed by the modernization steps inside the target's own virtual environment. They are not vendored in this repository and are not dependencies of this repository.

| Library | Licence | Notes |
|---|---|---|
| Flask | BSD 3-Clause | Installed from its public release into the target venv |
| Flask-RESTful | BSD 3-Clause | Installed from its public release into the target venv |
| SQLAlchemy | MIT | Installed from its public release into the target venv |

---

## Development dependency

| Package | Licence | Notes |
|---|---|---|
| pytest | MIT | The only development dependency of this repository; not required at runtime |

---

## Python standard library

All runtime code in this repository (`bobverified/`) uses only the Python standard library. No additional runtime dependencies are vendored or distributed.
