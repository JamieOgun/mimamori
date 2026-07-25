General Engineering Practices
Do not over-engineer and over-abstract in the initial implementation.
For any libraries, tools, frameworks used, try to use the latest version unless there is a specific reason not to.
Add necessary comment where the code is complex or implicit, but no need to comment on self-explanatory code.
Add test cases for code you added if suitable but start with the simplest possible test case first, no need to add too many complex test cases at once.
For Python Code
Python 3.12+

Use uv for package manager and virtual environment.

Use type hints and type checking where possible.

Use log library instead of raw print.

If you're building a cli-like tool, use "Click".

If you're building a server-like program, use "fastapi".

For any libraries such as sqlalchemy or httpx, use "async" version if possible.

Use google style docstrings for all functions and classes. But it doesn't mean you have to use it for all code, e.g., if the variable name is self-explanatory, you don't need to comment every variable of the function.

Some linting and formatting commands:

# Linting & formatting
uv run ruff check folder/
uv run ruff format folder/
uv run ruff check --fix folder/   # Auto-fix

# Type checking
uv run mypy folder/

# Import boundary enforcement
uv run lint-imports folder/
