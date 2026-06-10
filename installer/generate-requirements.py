import pathlib
import sys
import tomllib

pyproject_path = pathlib.Path(sys.argv[1])
requirements_path = pathlib.Path(sys.argv[2])
requirements_path.parent.mkdir(parents=True, exist_ok=True)
data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
dependencies = data.get("project", {}).get("dependencies", [])
requirements_path.write_text("\n".join(dependencies) + "\n", encoding="utf-8")
