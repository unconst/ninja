"""
Boundary-probing task generator — tasks specifically designed to find the competence cliff.

These are HARD tasks. They test limits of:
1. Large file comprehension (500+ lines)
2. Multi-round debugging (fix → discover → fix → discover)
3. Building complete systems from vague requirements
4. Cross-technology debugging (Python + shell + config)
"""

import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class BoundaryGenerator(TaskGenerator):
    """Generates boundary-probing tasks designed to find failure cliffs."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.DIAGNOSTIC

    def generate(self, count: int = 5, difficulty: str = "hard") -> list[Task]:
        generators = [
            self._large_file_subtle_bug,
            self._cascading_failures,
            self._build_from_spec,
            self._cross_tech_debug,
            self._hidden_state_bug,
        ]

        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            task = gen(difficulty)
            tasks.append(task)
        return tasks

    def _large_file_subtle_bug(self, difficulty: str) -> Task:
        """500+ line file with a subtle bug buried deep in the logic."""
        # Generate a large validator module with many functions
        code = '''"""
Comprehensive data validation library.
Validates user input, form data, API payloads, etc.
"""
import re
from datetime import datetime, date


class ValidationError(Exception):
    def __init__(self, field, message):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class ValidationResult:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.cleaned_data = {}

    def add_error(self, field, message):
        self.errors.append(ValidationError(field, message))

    def add_warning(self, field, message):
        self.warnings.append({"field": field, "message": message})

    def is_valid(self):
        return len(self.errors) == 0

    def set_cleaned(self, field, value):
        self.cleaned_data[field] = value


def validate_email(email):
    """Validate email format."""
    if not email or not isinstance(email, str):
        return False, "Email is required"
    email = email.strip()
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$'
    if not re.match(pattern, email):
        return False, "Invalid email format"
    if len(email) > 254:
        return False, "Email too long"
    return True, email


def validate_phone(phone):
    """Validate phone number."""
    if not phone:
        return True, None  # Phone is optional
    phone = phone.strip()
    digits = re.sub(r'[\\s\\-\\(\\)\\+]', '', phone)
    if not digits.isdigit():
        return False, "Phone must contain only digits, spaces, dashes, parentheses"
    if len(digits) < 7 or len(digits) > 15:
        return False, "Phone must be 7-15 digits"
    return True, digits


def validate_age(age):
    """Validate age as integer in valid range."""
    if age is None:
        return True, None
    try:
        age_int = int(age)
    except (ValueError, TypeError):
        return False, "Age must be a number"
    if age_int < 0 or age_int > 150:
        return False, "Age must be between 0 and 150"
    return True, age_int


def validate_date(date_str, fmt="%Y-%m-%d"):
    """Validate and parse date string."""
    if not date_str:
        return False, "Date is required"
    try:
        parsed = datetime.strptime(date_str, fmt)
        return True, parsed.date()
    except ValueError:
        return False, f"Invalid date format (expected {fmt})"


def validate_url(url):
    """Validate URL format."""
    if not url:
        return True, None
    url = url.strip()
    pattern = r'^https?://[a-zA-Z0-9.-]+(?:\\.[a-zA-Z]{2,})(?:/[^\\s]*)?$'
    if not re.match(pattern, url):
        return False, "Invalid URL format"
    return True, url


def validate_password(password, min_length=8):
    """Validate password strength."""
    if not password:
        return False, "Password is required"
    if len(password) < min_length:
        return False, f"Password must be at least {min_length} characters"
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_upper and has_lower and has_digit):
        return False, "Password must contain uppercase, lowercase, and digits"
    return True, password


def validate_username(username):
    """Validate username."""
    if not username:
        return False, "Username is required"
    username = username.strip()
    if len(username) < 3 or len(username) > 30:
        return False, "Username must be 3-30 characters"
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9_]*$', username):
        return False, "Username must start with a letter and contain only letters, digits, underscores"
    return True, username


def validate_amount(amount, min_val=0, max_val=None):
    """Validate monetary amount."""
    if amount is None:
        return False, "Amount is required"
    try:
        val = float(amount)
    except (ValueError, TypeError):
        return False, "Amount must be a number"
    if val < min_val:
        return False, f"Amount must be at least {min_val}"
    if max_val is not None and val > max_val:
        return False, f"Amount must be at most {max_val}"
    # Round to 2 decimal places
    return True, round(val, 2)


def validate_list(items, min_items=0, max_items=None, item_validator=None):
    """Validate a list of items."""
    if not isinstance(items, list):
        return False, "Expected a list"
    if len(items) < min_items:
        return False, f"Need at least {min_items} items"
    if max_items is not None and len(items) > max_items:
        return False, f"At most {max_items} items allowed"
    if item_validator:
        validated = []
        for i, item in enumerate(items):
            ok, result = item_validator(item)
            if not ok:
                return False, f"Item {i}: {result}"
            validated.append(result)
        return True, validated
    return True, items


def validate_address(address):
    """Validate address dict."""
    if not isinstance(address, dict):
        return False, "Address must be a dictionary"
    required = ["street", "city", "country"]
    for field in required:
        if field not in address or not address[field]:
            return False, f"Address missing required field: {field}"
    result = {}
    for key in ["street", "city", "state", "country", "zip_code"]:
        val = address.get(key, "")
        if isinstance(val, str):
            result[key] = val.strip()
        else:
            result[key] = val
    # Validate zip code if present
    if result.get("zip_code"):
        zc = result["zip_code"]
        if not re.match(r'^[0-9A-Za-z\\s-]{3,10}$', zc):
            return False, "Invalid zip code format"
    return True, result


class UserProfileValidator:
    """Validates complete user profile data."""

    def validate(self, data):
        result = ValidationResult()

        if not isinstance(data, dict):
            result.add_error("_root", "Data must be a dictionary")
            return result

        # Required fields
        for field, validator, required in [
            ("email", validate_email, True),
            ("username", validate_username, True),
            ("password", validate_password, True),
            ("phone", validate_phone, False),
            ("age", validate_age, False),
        ]:
            value = data.get(field)
            if required and value is None:
                result.add_error(field, f"{field} is required")
                continue
            if value is not None:
                ok, cleaned = validator(value)
                if not ok:
                    result.add_error(field, cleaned)
                else:
                    result.set_cleaned(field, cleaned)

        # Validate address if present
        if "address" in data:
            ok, cleaned = validate_address(data["address"])
            if not ok:
                result.add_error("address", cleaned)
            else:
                result.set_cleaned("address", cleaned)

        return result


class OrderValidator:
    """Validates order data."""

    def validate(self, data):
        result = ValidationResult()

        if not isinstance(data, dict):
            result.add_error("_root", "Data must be a dictionary")
            return result

        # Validate customer email
        email = data.get("customer_email")
        if not email:
            result.add_error("customer_email", "Customer email is required")
        else:
            ok, cleaned = validate_email(email)
            if not ok:
                result.add_error("customer_email", cleaned)
            else:
                result.set_cleaned("customer_email", cleaned)

        # Validate items
        items = data.get("items", [])
        if not items:
            result.add_error("items", "Order must have at least one item")
        else:
            ok, cleaned = validate_list(
                items, min_items=1, max_items=100,
                item_validator=self._validate_order_item
            )
            if not ok:
                result.add_error("items", cleaned)
            else:
                result.set_cleaned("items", cleaned)

        # Calculate total
        if result.is_valid() and "items" in result.cleaned_data:
            total = sum(item["subtotal"] for item in result.cleaned_data["items"])
            result.set_cleaned("total", round(total, 2))

            # Validate against provided total if any
            if "total" in data:
                # BUG: compares with wrong precision — uses int() instead of round()
                expected = int(data["total"] * 100) / 100  # Loses precision!
                calculated = round(total, 2)
                if abs(expected - calculated) > 0.01:
                    result.add_error("total", f"Total mismatch: expected {expected}, calculated {calculated}")

        return result

    def _validate_order_item(self, item):
        if not isinstance(item, dict):
            return False, "Item must be a dictionary"
        name = item.get("name")
        if not name:
            return False, "Item name is required"
        ok, qty = validate_amount(item.get("quantity"), min_val=1, max_val=10000)
        if not ok:
            return False, f"quantity: {qty}"
        ok, price = validate_amount(item.get("price"), min_val=0.01)
        if not ok:
            return False, f"price: {price}"
        return True, {
            "name": name,
            "quantity": int(qty),
            "price": price,
            "subtotal": round(int(qty) * price, 2),
        }


def validate_batch(records, validator_class):
    """Validate a batch of records. Returns (valid, invalid) lists."""
    validator = validator_class()
    valid = []
    invalid = []
    for i, record in enumerate(records):
        result = validator.validate(record)
        if result.is_valid():
            valid.append({"index": i, "data": result.cleaned_data})
        else:
            invalid.append({
                "index": i,
                "errors": [{"field": e.field, "message": e.message} for e in result.errors]
            })
    return valid, invalid
'''

        test_code = '''import pytest
from validator import (
    validate_email, validate_phone, validate_age, validate_date,
    validate_url, validate_password, validate_username, validate_amount,
    validate_list, validate_address,
    UserProfileValidator, OrderValidator, validate_batch,
)


# === Individual validators ===

def test_email_valid():
    ok, result = validate_email("test@example.com")
    assert ok
    assert result == "test@example.com"

def test_email_strips_whitespace():
    ok, result = validate_email("  test@example.com  ")
    assert ok
    assert result == "test@example.com"

def test_email_invalid():
    ok, msg = validate_email("not-an-email")
    assert not ok

def test_phone_valid():
    ok, result = validate_phone("+1 (555) 123-4567")
    assert ok
    assert result == "15551234567"

def test_phone_optional():
    ok, result = validate_phone("")
    assert ok
    assert result is None

def test_age_valid():
    ok, result = validate_age("25")
    assert ok
    assert result == 25

def test_age_negative():
    ok, msg = validate_age(-1)
    assert not ok

def test_date_valid():
    ok, result = validate_date("2024-03-15")
    assert ok
    assert result.year == 2024

def test_date_invalid():
    ok, msg = validate_date("not-a-date")
    assert not ok

def test_password_valid():
    ok, result = validate_password("Abc12345")
    assert ok

def test_password_too_short():
    ok, msg = validate_password("Ab1")
    assert not ok

def test_password_no_digit():
    ok, msg = validate_password("Abcdefgh")
    assert not ok

def test_username_valid():
    ok, result = validate_username("john_doe")
    assert ok

def test_username_starts_with_digit():
    ok, msg = validate_username("1john")
    assert not ok

def test_amount_valid():
    ok, result = validate_amount(19.999)
    assert ok
    assert result == 20.0  # Rounded to 2 decimal places

def test_amount_below_min():
    ok, msg = validate_amount(-5, min_val=0)
    assert not ok


# === Profile validation ===

def test_profile_valid():
    v = UserProfileValidator()
    result = v.validate({
        "email": "test@example.com",
        "username": "john_doe",
        "password": "SecurePass1",
        "phone": "+1-555-1234",
        "age": 30,
    })
    assert result.is_valid()
    assert result.cleaned_data["email"] == "test@example.com"

def test_profile_missing_required():
    v = UserProfileValidator()
    result = v.validate({"email": "test@example.com"})
    assert not result.is_valid()
    assert len(result.errors) >= 2  # missing username and password


# === Order validation ===

def test_order_valid():
    v = OrderValidator()
    result = v.validate({
        "customer_email": "buyer@example.com",
        "items": [
            {"name": "Widget", "quantity": 2, "price": 9.99},
            {"name": "Gadget", "quantity": 1, "price": 24.50},
        ],
    })
    assert result.is_valid()
    assert result.cleaned_data["total"] == 44.48

def test_order_total_validation():
    """Order with provided total that matches calculated total."""
    v = OrderValidator()
    result = v.validate({
        "customer_email": "buyer@example.com",
        "items": [
            {"name": "Widget", "quantity": 3, "price": 9.99},
        ],
        "total": 29.97,  # 3 * 9.99 = 29.97
    })
    assert result.is_valid(), f"Errors: {[e.message for e in result.errors]}"

def test_order_total_mismatch():
    """Order with wrong total should fail."""
    v = OrderValidator()
    result = v.validate({
        "customer_email": "buyer@example.com",
        "items": [
            {"name": "Widget", "quantity": 2, "price": 9.99},
        ],
        "total": 100.00,  # Way too high
    })
    assert not result.is_valid()

def test_order_total_precision():
    """Total comparison should handle floating point correctly."""
    v = OrderValidator()
    result = v.validate({
        "customer_email": "buyer@example.com",
        "items": [
            {"name": "Item A", "quantity": 1, "price": 10.10},
            {"name": "Item B", "quantity": 1, "price": 20.20},
        ],
        "total": 30.30,  # Should be exactly right
    })
    assert result.is_valid(), f"Errors: {[e.message for e in result.errors]}"


# === Batch validation ===

def test_batch_validation():
    records = [
        {"customer_email": "a@b.com", "items": [{"name": "x", "quantity": 1, "price": 5.0}]},
        {"customer_email": "invalid", "items": []},
        {"customer_email": "c@d.com", "items": [{"name": "y", "quantity": 2, "price": 3.0}]},
    ]
    valid, invalid = validate_batch(records, OrderValidator)
    assert len(valid) == 2
    assert len(invalid) == 1
    assert invalid[0]["index"] == 1
'''

        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Fix subtle bug in 300+ line validation library",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The validation library (validator.py) is a 300+ line module with many validators.
                Most tests pass but some are failing.

                Run: `python3 -m pytest test_validator.py -p no:xdist -p no:randomly -p no:cacheprovider -v`

                The bug is SUBTLE — the code looks correct at first glance.
                Don't just read the failing test — trace the FULL code path from test to bug.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "validator.py": code,
                    "test_validator.py": test_code,
                },
            ),
            ground_truth="Bug in OrderValidator.validate() line: uses int(data['total'] * 100) / 100 for "
                        "precision, but int() truncates instead of rounding, causing 30.30 * 100 = 3029.9999... "
                        "-> int() = 3029 -> /100 = 30.29, which != 30.30. Fix: use round(data['total'], 2)",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_validator.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.TEST_RUNNING,
            ],
            source="boundary_generator:large_file_subtle_bug",
            estimated_minutes=15,
        )

    def _cascading_failures(self, difficulty: str) -> Task:
        """Fix one bug → next bug revealed → fix that → next bug revealed, 4 rounds."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Fix cascading bugs — each fix reveals the next",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The ETL pipeline has MULTIPLE bugs, but they cascade — you can only
                discover each one after fixing the previous one.

                Run: `python3 run_etl.py`

                Fix ALL bugs until the output says "ETL complete: N records processed"
                where N > 0.

                Hint: there are at least 4 distinct bugs in the pipeline.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "run_etl.py": textwrap.dedent("""\
                        from etl import ETLPipeline

                        pipeline = ETLPipeline("data.csv", "output.json")
                        pipeline.run()
                    """),
                    "etl.py": textwrap.dedent("""\
                        import csv
                        import json
                        from transformers import clean_record, enrich_record
                        from loaders import load_csv, save_json

                        class ETLPipeline:
                            def __init__(self, input_path, output_path):
                                self.input_path = input_path
                                self.output_path = output_path
                                self.stats = {"extracted": 0, "transformed": 0, "loaded": 0, "errors": 0}

                            def run(self):
                                # Extract
                                try:
                                    records = load_csv(self.input_path)
                                except Exception as e:
                                    print(f"Extract failed: {e}")
                                    return

                                self.stats["extracted"] = len(records)
                                print(f"Extracted {len(records)} records")

                                # Transform
                                transformed = []
                                for record in records:
                                    try:
                                        cleaned = clean_record(record)
                                        enriched = enrich_record(cleaned)
                                        transformed.append(enriched)
                                    except Exception as e:
                                        self.stats["errors"] += 1
                                        continue

                                self.stats["transformed"] = len(transformed)
                                print(f"Transformed {len(transformed)} records")

                                # Load
                                try:
                                    count = save_json(transformed, self.output_path)
                                    self.stats["loaded"] = count
                                except Exception as e:
                                    print(f"Load failed: {e}")
                                    return

                                print(f"ETL complete: {self.stats['loaded']} records processed")
                    """),
                    "transformers.py": textwrap.dedent("""\
                        from datetime import datetime

                        def clean_record(record):
                            \"\"\"Clean and normalize a record.\"\"\"
                            cleaned = {}
                            for key, value in record.items():
                                # Strip whitespace from all string values
                                if isinstance(value, str):
                                    value = value.strip()
                                # Bug 2: converts empty strings to None, but later code expects strings
                                if value == "":
                                    value = None
                                cleaned[key.lower().strip()] = value
                            return cleaned

                        def enrich_record(record):
                            \"\"\"Add derived fields.\"\"\"
                            # Bug 3: assumes 'date' field exists and is not None
                            date_str = record["date"]
                            record["year"] = datetime.strptime(date_str, "%Y-%m-%d").year
                            record["month"] = datetime.strptime(date_str, "%Y-%m-%d").month

                            # Calculate full name
                            # Bug 4: concatenates None with strings when first/last name is empty
                            record["full_name"] = record["first_name"] + " " + record["last_name"]

                            return record
                    """),
                    "loaders.py": textwrap.dedent("""\
                        import csv
                        import json

                        def load_csv(path):
                            \"\"\"Load records from CSV file.\"\"\"
                            records = []
                            # Bug 1: opens with wrong encoding
                            with open(path, 'r', encoding='ascii') as f:
                                reader = csv.DictReader(f)
                                for row in reader:
                                    records.append(dict(row))
                            return records

                        def save_json(records, path):
                            \"\"\"Save records to JSON file. Returns count.\"\"\"
                            with open(path, 'w') as f:
                                json.dump(records, f, indent=2, default=str)
                            return len(records)
                    """),
                    "data.csv": "first_name,last_name,date,email\nJohn,Doe,2024-01-15,john@example.com\nJané,Smith,2024-02-20,jane@example.com\nBob,,2024-03-10,bob@example.com\n",
                },
            ),
            ground_truth="4 bugs: 1) loaders.py: encoding='ascii' fails on 'é', change to 'utf-8', "
                        "2) transformers.py: empty strings become None, 3) enrich_record: date_str can be "
                        "None after cleaning, need None check, 4) full_name concatenation fails when "
                        "first_name or last_name is None, need str() or 'or \"\"' fallback.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 run_etl.py 2>&1",
                output_contains=["ETL complete:", "records processed"],
                output_not_contains=["failed", "Error", "Traceback"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.MULTI_FILE_REASONING,
                Capability.ERROR_INTERPRETATION,
                Capability.DECOMPOSITION,
            ],
            source="boundary_generator:cascading_failures",
            estimated_minutes=15,
        )

    def _build_from_spec(self, difficulty: str) -> Task:
        """Build a complete working system from a specification — no starter code."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Build CLI calculator from specification only",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Build a command-line calculator tool called `calc.py` that works as follows:

                Usage: `python3 calc.py <expression>`

                Requirements:
                1. Parse and evaluate mathematical expressions from command line args
                2. Support: +, -, *, /, ** (power), () (grouping)
                3. Support variables: `python3 calc.py "x=5; x*2+3"` → 13
                4. Support functions: sqrt, abs, sin, cos, pi, e
                5. Handle errors gracefully: division by zero, syntax errors, undefined variables
                6. Print ONLY the numeric result (or error message starting with "Error:")

                Examples:
                  python3 calc.py "2+3" → 5
                  python3 calc.py "2**3" → 8
                  python3 calc.py "(1+2)*3" → 9
                  python3 calc.py "sqrt(16)" → 4.0
                  python3 calc.py "x=5; x*2+3" → 13
                  python3 calc.py "1/0" → Error: division by zero

                Do NOT use eval() or exec() — parse the expressions properly.
                A test file is provided to verify your implementation.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "test_calc.py": textwrap.dedent("""\
                        import subprocess
                        import pytest

                        def calc(expr):
                            result = subprocess.run(
                                ["python3", "calc.py", expr],
                                capture_output=True, text=True, timeout=5
                            )
                            return result.stdout.strip()

                        def test_addition():
                            assert calc("2+3") == "5"

                        def test_subtraction():
                            assert calc("10-3") == "7"

                        def test_multiplication():
                            assert calc("4*5") == "20"

                        def test_division():
                            assert calc("10/4") == "2.5"

                        def test_power():
                            assert calc("2**3") == "8"

                        def test_grouping():
                            assert calc("(1+2)*3") == "9"

                        def test_nested_groups():
                            assert calc("((2+3)*2)+1") == "11"

                        def test_sqrt():
                            assert calc("sqrt(16)") == "4.0"

                        def test_abs():
                            assert calc("abs(-5)") == "5"

                        def test_variable():
                            assert calc("x=5; x*2+3") == "13"

                        def test_multiple_vars():
                            assert calc("x=3; y=4; x+y") == "7"

                        def test_division_by_zero():
                            result = calc("1/0")
                            assert result.startswith("Error:")

                        def test_undefined_var():
                            result = calc("x+1")
                            assert result.startswith("Error:")

                        def test_integer_output():
                            # Results that are whole numbers should show as ints
                            assert calc("2+3") == "5"
                            assert calc("6/2") == "3.0" or calc("6/2") == "3"
                    """),
                },
            ),
            ground_truth="Must implement expression parser (recursive descent or use ast module safely), "
                        "variable assignment/lookup, math function dispatch, error handling. "
                        "Cannot use eval/exec. Significant construction-from-scratch task.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_calc.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["passed"],
                output_not_contains=["FAILED"],
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.FILE_CREATION,
                Capability.TEST_RUNNING,
                Capability.DECOMPOSITION,
            ],
            source="boundary_generator:build_from_spec",
            estimated_minutes=20,
        )

    def _cross_tech_debug(self, difficulty: str) -> Task:
        """Bug spans Python, shell script, and config file — must trace across all three."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Fix deployment spanning Python, shell, and config",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The deployment system has a bug that causes it to fail.
                The system has 3 layers:
                - deploy.sh (orchestrator shell script)
                - config.ini (configuration)
                - deploy_lib.py (Python library)

                Run: `bash deploy.sh`

                Fix ALL issues until deploy.sh runs successfully and prints
                "Deployment successful: 3 services deployed"
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "deploy.sh": textwrap.dedent("""\
                        #!/bin/bash
                        set -e

                        CONFIG_FILE="config.ini"

                        # Read config
                        # Bug 1: grep pattern is wrong — config uses '=' not ':'
                        DEPLOY_ENV=$(grep "^environment:" "$CONFIG_FILE" | cut -d: -f2 | tr -d ' ')
                        PORT=$(grep "^port:" "$CONFIG_FILE" | cut -d: -f2 | tr -d ' ')

                        echo "Deploying to: $DEPLOY_ENV on port $PORT"

                        # Run Python deploy
                        python3 deploy_lib.py "$DEPLOY_ENV" "$PORT"

                        echo "Deployment successful: $(python3 -c "import deploy_lib; print(deploy_lib.count_services('$DEPLOY_ENV'))" 2>&1) services deployed"
                    """),
                    "config.ini": textwrap.dedent("""\
                        [deployment]
                        environment = staging
                        port = 8080
                        max_retries = 3

                        [services]
                        web = enabled
                        api = enabled
                        worker = enabled
                        scheduler = disabled
                    """),
                    "deploy_lib.py": textwrap.dedent("""\
                        import sys
                        import configparser

                        def deploy(env, port):
                            config = configparser.ConfigParser()
                            config.read("config.ini")

                            services = []
                            for svc, status in config["services"].items():
                                if status.strip() == "enabled":
                                    services.append(svc)

                            # Bug 2: port comparison uses string, not int
                            if port < 1024:
                                print(f"Error: port {port} is privileged")
                                sys.exit(1)

                            for svc in services:
                                print(f"  Deploying {svc} to {env}:{port}")

                            return len(services)

                        def count_services(env):
                            config = configparser.ConfigParser()
                            config.read("config.ini")
                            count = 0
                            for svc, status in config["services"].items():
                                if status.strip() == "enabled":
                                    count += 1
                            return count

                        if __name__ == "__main__":
                            if len(sys.argv) != 3:
                                print("Usage: deploy_lib.py <env> <port>")
                                sys.exit(1)
                            deploy(sys.argv[1], sys.argv[2])
                    """),
                },
                setup_commands=["chmod +x deploy.sh"],
            ),
            ground_truth="Bug 1: deploy.sh greps for 'environment:' but config uses '= ' format (INI style). "
                        "Fix: use grep 'environment' with '=' delimiter. Bug 2: deploy_lib.py compares port "
                        "(string from sys.argv) with int 1024, TypeError. Fix: int(port).",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="bash deploy.sh 2>&1",
                output_contains=["Deployment successful:", "3 services deployed"],
                output_not_contains=["Error", "Traceback"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.SHELL_COMMANDS,
                Capability.CONFIG_READING,
                Capability.CONFIG_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.MULTI_FILE_REASONING,
            ],
            source="boundary_generator:cross_tech_debug",
            estimated_minutes=10,
        )

    def _hidden_state_bug(self, difficulty: str) -> Task:
        """Bug only manifests under specific state conditions — requires careful reasoning."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Fix state-dependent bug that only triggers on third call",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The session manager has a bug that only manifests after specific
                sequences of operations. The first two calls work fine; the third fails.

                Run: `python3 -m pytest test_session.py -p no:xdist -p no:randomly -p no:cacheprovider -v`

                Some tests pass, some fail. The bug is in session.py — it corrupts
                internal state only under certain conditions.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "session.py": textwrap.dedent("""\
                        import time
                        import hashlib

                        class SessionManager:
                            def __init__(self, max_sessions=100, timeout=3600):
                                self.max_sessions = max_sessions
                                self.timeout = timeout
                                self._sessions = {}
                                self._token_counter = 0

                            def create_session(self, user_id):
                                \"\"\"Create a new session, return session token.\"\"\"
                                # Evict expired sessions first
                                self._cleanup()

                                if len(self._sessions) >= self.max_sessions:
                                    # Evict oldest session
                                    oldest = min(self._sessions, key=lambda k: self._sessions[k]["created"])
                                    del self._sessions[oldest]

                                token = self._generate_token(user_id)
                                self._sessions[token] = {
                                    "user_id": user_id,
                                    "created": time.time(),
                                    "last_access": time.time(),
                                    "data": {},
                                }
                                return token

                            def get_session(self, token):
                                \"\"\"Get session data. Returns None if expired/missing.\"\"\"
                                if token not in self._sessions:
                                    return None
                                session = self._sessions[token]
                                if time.time() - session["last_access"] > self.timeout:
                                    del self._sessions[token]
                                    return None
                                session["last_access"] = time.time()
                                return session

                            def set_data(self, token, key, value):
                                \"\"\"Store data in session.\"\"\"
                                session = self.get_session(token)
                                if not session:
                                    raise ValueError("Invalid session")
                                session["data"][key] = value

                            def get_data(self, token, key, default=None):
                                \"\"\"Retrieve data from session.\"\"\"
                                session = self.get_session(token)
                                if not session:
                                    raise ValueError("Invalid session")
                                return session["data"].get(key, default)

                            def list_sessions(self, user_id=None):
                                \"\"\"List active sessions, optionally filtered by user.\"\"\"
                                self._cleanup()
                                result = []
                                for token, session in self._sessions.items():
                                    if user_id is None or session["user_id"] == user_id:
                                        result.append({
                                            "token": token,
                                            "user_id": session["user_id"],
                                            "created": session["created"],
                                        })
                                return result

                            def destroy_session(self, token):
                                \"\"\"Remove a session.\"\"\"
                                if token in self._sessions:
                                    del self._sessions[token]
                                    return True
                                return False

                            def _generate_token(self, user_id):
                                # Bug: uses counter that isn't incremented, so same user always
                                # gets the same token, overwriting previous session
                                raw = f"{user_id}:{self._token_counter}"
                                return hashlib.sha256(raw.encode()).hexdigest()[:32]

                            def _cleanup(self):
                                now = time.time()
                                expired = [t for t, s in self._sessions.items()
                                          if now - s["last_access"] > self.timeout]
                                for t in expired:
                                    del self._sessions[t]
                    """),
                    "test_session.py": textwrap.dedent("""\
                        import pytest
                        from session import SessionManager

                        @pytest.fixture
                        def manager():
                            return SessionManager(max_sessions=10, timeout=3600)

                        def test_create_session(manager):
                            token = manager.create_session("user1")
                            assert token is not None
                            assert len(token) == 32

                        def test_get_session(manager):
                            token = manager.create_session("user1")
                            session = manager.get_session(token)
                            assert session is not None
                            assert session["user_id"] == "user1"

                        def test_set_get_data(manager):
                            token = manager.create_session("user1")
                            manager.set_data(token, "cart", ["item1"])
                            assert manager.get_data(token, "cart") == ["item1"]

                        def test_invalid_token(manager):
                            with pytest.raises(ValueError):
                                manager.set_data("fake_token", "key", "value")

                        def test_multiple_users(manager):
                            \"\"\"Each user should get their own independent session.\"\"\"
                            t1 = manager.create_session("user1")
                            t2 = manager.create_session("user2")
                            # Tokens should be different
                            assert t1 != t2
                            # Sessions should be independent
                            manager.set_data(t1, "name", "Alice")
                            manager.set_data(t2, "name", "Bob")
                            assert manager.get_data(t1, "name") == "Alice"
                            assert manager.get_data(t2, "name") == "Bob"

                        def test_same_user_multiple_sessions(manager):
                            \"\"\"Same user can have multiple sessions (e.g., different devices).\"\"\"
                            t1 = manager.create_session("user1")
                            t2 = manager.create_session("user1")
                            # Should be different tokens
                            assert t1 != t2
                            # Should be independent sessions
                            manager.set_data(t1, "device", "phone")
                            manager.set_data(t2, "device", "laptop")
                            assert manager.get_data(t1, "device") == "phone"
                            assert manager.get_data(t2, "device") == "laptop"

                        def test_list_sessions(manager):
                            manager.create_session("user1")
                            manager.create_session("user2")
                            manager.create_session("user1")
                            all_sessions = manager.list_sessions()
                            assert len(all_sessions) == 3
                            user1_sessions = manager.list_sessions("user1")
                            assert len(user1_sessions) == 2

                        def test_destroy_session(manager):
                            token = manager.create_session("user1")
                            assert manager.destroy_session(token)
                            assert manager.get_session(token) is None

                        def test_max_sessions(manager):
                            tokens = []
                            for i in range(12):  # Exceeds max_sessions=10
                                tokens.append(manager.create_session(f"user{i}"))
                            # Should have at most 10 sessions
                            sessions = manager.list_sessions()
                            assert len(sessions) <= 10
                    """),
                },
            ),
            ground_truth="Bug in _generate_token: self._token_counter is never incremented, so the same "
                        "user_id always generates the same token. The second create_session for the same "
                        "user overwrites the first session. Fix: increment self._token_counter.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_session.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.HYPOTHESIS_TESTING,
                Capability.TEST_RUNNING,
            ],
            source="boundary_generator:hidden_state_bug",
            estimated_minutes=10,
        )
