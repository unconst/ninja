"""
Data analysis task generator.

Generates tasks involving CSV/JSON data processing, statistical analysis,
data cleaning, and artifact generation (reports, transformed datasets).
"""

import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class DataAnalysisGenerator(TaskGenerator):
    """Generates data analysis and transformation tasks."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.DATA_ANALYSIS

    def generate(self, count: int = 5, difficulty: str = "medium") -> list[Task]:
        generators = [
            self._outlier_detection,
            self._data_cleaning,
            self._join_and_aggregate,
            self._time_series_analysis,
            self._pivot_report,
            self._missing_data_imputation,
            self._deduplication,
            self._schema_validation,
        ]
        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            tasks.append(gen(difficulty))
        return tasks

    def _outlier_detection(self, difficulty: str) -> Task:
        """Task: find and report outliers in a dataset."""
        csv_data = textwrap.dedent("""\
            timestamp,sensor_id,temperature,humidity,pressure
            2024-01-01 00:00,S1,22.1,45.0,1013.2
            2024-01-01 01:00,S1,21.8,46.2,1013.1
            2024-01-01 02:00,S1,21.5,47.1,1013.0
            2024-01-01 03:00,S1,999.9,45.5,1013.1
            2024-01-01 04:00,S1,21.0,48.0,1012.9
            2024-01-01 05:00,S1,20.8,-1.0,1012.8
            2024-01-01 00:00,S2,23.5,42.0,1013.5
            2024-01-01 01:00,S2,23.2,43.1,1013.4
            2024-01-01 02:00,S2,23.0,0.0,1013.3
            2024-01-01 03:00,S2,22.8,44.0,1013.2
            2024-01-01 04:00,S2,22.5,43.5,1013.1
            2024-01-01 05:00,S2,22.3,43.0,0.0
        """)

        return Task(
            category=TaskCategory.DATA_ANALYSIS,
            title="Detect and report sensor data outliers",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Analyze sensors.csv which contains temperature, humidity, and pressure
                readings from IoT sensors. Some readings contain obvious errors/outliers.

                Write a script that:
                1. Identifies outlier values (physically impossible or statistically anomalous)
                2. Creates outliers.json listing each outlier with:
                   - row number, sensor_id, column name, value, reason
                3. Creates cleaned.csv with outliers replaced by interpolated values
                   (average of the preceding and following value for that sensor)

                Run the script to produce the output files.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={"sensors.csv": csv_data},
            ),
            ground_truth="Outliers: S1 temp 999.9 (row 4), S1 humidity -1.0 (row 6), S2 humidity 0.0 (row 9), S2 pressure 0.0 (row 12). Cleaned values should be interpolated.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["outliers.json", "cleaned.csv"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import json; d=json.load(open('outliers.json')); assert len(d)>=3; print(f'found_{len(d)}_outliers')\"",
                     "output_contains": ["found_"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import csv; rows=list(csv.DictReader(open('cleaned.csv'))); assert float(rows[3]['temperature'])<100; print('cleaned_ok')\"",
                     "output_contains": ["cleaned_ok"]},
                ]
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.SCRIPT_WRITING,
                Capability.FILE_CREATION,
                Capability.SHELL_COMMANDS,
                Capability.ROOT_CAUSE_ANALYSIS,
            ],
            source="data_analysis_generator:outlier_detection",
            estimated_minutes=8,
        )

    def _data_cleaning(self, difficulty: str) -> Task:
        """Task: clean messy real-world data."""
        csv_data = textwrap.dedent("""\
            Name,Email,Phone,Signup Date,Plan
            Alice Smith,alice@example.com,(555) 123-4567,2024-01-15,premium
            Bob Jones,bob@example,555.234.5678,Jan 20 2024,basic
            Charlie Brown,charlie@example.com,5553456789,2024-02-01,Premium
            ,diana@example.com,(555) 456-7890,2024-02-15,basic
            Eve Wilson,eve@example.com,(555) 567-8901,2024/03/01,BASIC
            Frank,,5556789012,March 15 2024,premium
            Grace Lee,grace@example.com,(555) 678-9012,2024-04-01,basic
            Henry Ford,henry@example.com,(555) 789-0123,2024-04-15,unknown
            Iris Chang,iris@example.com,N/A,04-30-2024,premium
            Jack Ma,jack@example.com,(555) 890-1234,,basic
        """)

        return Task(
            category=TaskCategory.DATA_ANALYSIS,
            title="Clean and normalize user registration data",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The users.csv file has messy data with inconsistent formats and missing values.
                Write a cleaning script and produce a clean_users.csv with:

                1. Standardize phone numbers to format: (555) 123-4567 (or empty if invalid/missing)
                2. Validate emails (must have @ and a domain with a dot)
                3. Standardize dates to YYYY-MM-DD format
                4. Normalize plan names to lowercase: 'basic' or 'premium' (set 'unknown' to empty)
                5. Flag rows with missing required fields (Name, Email) in a separate issues.csv
                   with columns: row_number, field, issue

                Empty/invalid values should be set to empty string, not removed.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={"users.csv": csv_data},
            ),
            ground_truth="clean_users.csv with normalized phones, validated emails (bob@example invalid), standardized dates, lowercase plans. issues.csv with missing name (row 4), missing email (row 7), invalid email (row 2), missing date (row 10).",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["clean_users.csv", "issues.csv"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import csv; r=list(csv.DictReader(open('clean_users.csv'))); assert r[0]['Plan']=='premium'; assert r[4]['Plan']=='basic'; print('plans_ok')\"",
                     "output_contains": ["plans_ok"]},
                    {"method": "command_output",
                     "check_command": "wc -l < issues.csv",
                     "output_contains": []},
                ]
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.SCRIPT_WRITING,
                Capability.FILE_CREATION,
                Capability.DECOMPOSITION,
            ],
            source="data_analysis_generator:data_cleaning",
            estimated_minutes=8,
        )

    def _join_and_aggregate(self, difficulty: str) -> Task:
        """Task: join multiple data files and compute aggregates."""
        orders = textwrap.dedent("""\
            order_id,customer_id,product_id,quantity,order_date
            1001,C1,P1,2,2024-01-10
            1002,C2,P3,1,2024-01-11
            1003,C1,P2,3,2024-01-12
            1004,C3,P1,1,2024-01-15
            1005,C2,P2,2,2024-01-16
            1006,C1,P3,1,2024-01-20
            1007,C3,P3,4,2024-01-22
            1008,C2,P1,1,2024-01-25
        """)

        products = textwrap.dedent("""\
            product_id,name,price,category
            P1,Widget A,29.99,widgets
            P2,Gadget B,49.99,gadgets
            P3,Doohickey C,19.99,accessories
        """)

        customers = textwrap.dedent("""\
            customer_id,name,email,tier
            C1,Alice,alice@example.com,gold
            C2,Bob,bob@example.com,silver
            C3,Charlie,charlie@example.com,bronze
        """)

        return Task(
            category=TaskCategory.DATA_ANALYSIS,
            title="Join data files and compute sales report",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                You have three CSV files: orders.csv, products.csv, and customers.csv.
                Write a script that joins them and produces:

                1. sales_report.csv with columns:
                   customer_name, customer_tier, total_orders, total_spent, favorite_category
                   (sorted by total_spent descending)

                2. product_summary.csv with columns:
                   product_name, category, units_sold, revenue
                   (sorted by revenue descending)

                Calculate total_spent as sum(quantity * price). favorite_category is the
                category they spent the most on.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "orders.csv": orders,
                    "products.csv": products,
                    "customers.csv": customers,
                },
            ),
            ground_truth="Alice: 3 orders, $209.93 total (2*29.99+3*49.99+1*19.99). Bob: 3 orders, $149.96. Charlie: 2 orders, $109.95. Product: Gadget B revenue=$249.95 (5 units).",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["sales_report.csv", "product_summary.csv"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import csv; r=list(csv.DictReader(open('sales_report.csv'))); assert r[0]['customer_name']=='Alice'; print('top_customer_ok')\"",
                     "output_contains": ["top_customer_ok"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import csv; r=list(csv.DictReader(open('product_summary.csv'))); assert len(r)==3; print('products_ok')\"",
                     "output_contains": ["products_ok"]},
                ]
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.SCRIPT_WRITING,
                Capability.FILE_CREATION,
                Capability.MULTI_FILE_REASONING,
                Capability.DECOMPOSITION,
            ],
            source="data_analysis_generator:join_and_aggregate",
            estimated_minutes=8,
        )

    def _time_series_analysis(self, difficulty: str) -> Task:
        """Task: analyze time series data and detect patterns."""
        import random
        random.seed(42)
        lines = ["date,pageviews,signups,revenue"]
        base_views = 1000
        for day in range(1, 31):
            date = f"2024-01-{day:02d}"
            # Weekday pattern (lower on weekends)
            dow = (day - 1) % 7  # 0=Mon
            weekend_factor = 0.6 if dow >= 5 else 1.0
            views = int(base_views * weekend_factor + random.randint(-100, 100))
            signups = max(0, int(views * 0.05 + random.randint(-5, 5)))
            revenue = round(signups * 29.99 + random.uniform(-50, 50), 2)
            # Inject anomaly on day 17
            if day == 17:
                views = 3500
                signups = 180
                revenue = 5398.20
            lines.append(f"{date},{views},{signups},{revenue}")

        return Task(
            category=TaskCategory.DATA_ANALYSIS,
            title="Analyze web traffic time series and detect anomaly",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Analyze metrics.csv containing daily web metrics (pageviews, signups, revenue).

                Create analysis.json with:
                1. "summary": avg_pageviews, avg_signups, avg_revenue (for the full period)
                2. "weekday_vs_weekend": compare average metrics for weekdays vs weekends
                3. "anomalies": list of dates with any metric more than 2 standard deviations
                   from the mean, with the anomalous metric name and value
                4. "trend": whether pageviews are "increasing", "decreasing", or "stable"
                   over the period (use first vs last week averages)

                Use only the Python standard library.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={"metrics.csv": "\n".join(lines) + "\n"},
            ),
            ground_truth="Anomaly on 2024-01-17 (all metrics spike). Weekend traffic ~60% of weekday. Trend should be stable.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["analysis.json"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import json; d=json.load(open('analysis.json')); assert 'summary' in d; assert 'anomalies' in d; assert len(d['anomalies'])>=1; print('analysis_ok')\"",
                     "output_contains": ["analysis_ok"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import json; d=json.load(open('analysis.json')); dates=[a.get('date','') for a in d['anomalies']]; assert '2024-01-17' in dates; print('anomaly_detected')\"",
                     "output_contains": ["anomaly_detected"]},
                ]
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.SCRIPT_WRITING,
                Capability.FILE_CREATION,
                Capability.DECOMPOSITION,
                Capability.ROOT_CAUSE_ANALYSIS,
            ],
            source="data_analysis_generator:time_series_analysis",
            estimated_minutes=10,
        )

    def _pivot_report(self, difficulty: str) -> Task:
        """Task: create a pivot table/cross-tab report."""
        sales = textwrap.dedent("""\
            date,region,product,units,revenue
            2024-01-05,North,Widget,10,299.90
            2024-01-05,South,Widget,8,239.92
            2024-01-05,North,Gadget,5,249.95
            2024-01-12,South,Gadget,3,149.97
            2024-01-12,North,Widget,12,359.88
            2024-01-12,East,Widget,6,179.94
            2024-01-19,North,Gadget,7,349.93
            2024-01-19,South,Widget,9,269.91
            2024-01-19,East,Gadget,4,199.96
            2024-01-26,North,Widget,15,449.85
            2024-01-26,South,Gadget,6,299.94
            2024-01-26,East,Widget,8,239.92
        """)

        return Task(
            category=TaskCategory.DATA_ANALYSIS,
            title="Create pivot table report from sales data",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                From sales.csv, create two reports:

                1. pivot_region.csv: Rows = regions, Columns = products
                   Values = total revenue. Include a "Total" column.

                2. pivot_weekly.csv: Rows = week number (1-4), Columns = regions
                   Values = total units sold. Include a "Total" column.

                Format all revenue values to 2 decimal places. Sort rows alphabetically
                (or numerically for weeks).
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={"sales.csv": sales},
            ),
            ground_truth="North total: 1709.51, South total: 959.74, East total: 619.82. Week 1: 24 units total.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["pivot_region.csv", "pivot_weekly.csv"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import csv; r=list(csv.DictReader(open('pivot_region.csv'))); print(len(r)); assert len(r)>=3; print('pivot_ok')\"",
                     "output_contains": ["pivot_ok"]},
                ]
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.SCRIPT_WRITING,
                Capability.FILE_CREATION,
                Capability.DECOMPOSITION,
            ],
            source="data_analysis_generator:pivot_report",
            estimated_minutes=8,
        )

    def _missing_data_imputation(self, difficulty: str) -> Task:
        """Task: handle missing data intelligently."""
        csv_data = textwrap.dedent("""\
            student_id,name,math,science,english,history,art
            S001,Alice,92,88,85,,78
            S002,Bob,,76,90,82,
            S003,Charlie,78,82,,88,92
            S004,Diana,95,91,88,85,80
            S005,Eve,88,,79,76,85
            S006,Frank,72,68,75,70,
            S007,Grace,,85,92,88,90
            S008,Henry,85,80,,72,68
        """)

        return Task(
            category=TaskCategory.DATA_ANALYSIS,
            title="Handle missing grades with imputation strategy",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The grades.csv file has missing values (empty cells = no grade recorded).
                Write a script that:

                1. Produces missing_report.txt listing each missing value:
                   student name, subject, and whether it's imputable
                2. Impute missing values using each student's average of their other subjects
                   (round to nearest integer)
                3. Save the complete dataset as complete_grades.csv
                4. Calculate and save class_averages.json with the average grade per subject
                   (using imputed values), rounded to 1 decimal place
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={"grades.csv": csv_data},
            ),
            ground_truth="7 missing values. Alice art avg of others = ~86. Bob math avg = ~83. Complete dataset has no empty cells. Class averages should be computed from imputed data.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": [
                        "missing_report.txt", "complete_grades.csv", "class_averages.json"
                    ]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import csv; r=list(csv.DictReader(open('complete_grades.csv'))); assert all(row['math'] for row in r); assert all(row['science'] for row in r); print('complete_ok')\"",
                     "output_contains": ["complete_ok"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import json; d=json.load(open('class_averages.json')); assert 'math' in d; assert 'science' in d; print('averages_ok')\"",
                     "output_contains": ["averages_ok"]},
                ]
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.SCRIPT_WRITING,
                Capability.FILE_CREATION,
                Capability.DECOMPOSITION,
                Capability.SUMMARY_GENERATION,
            ],
            source="data_analysis_generator:missing_data_imputation",
            estimated_minutes=8,
        )

    def _deduplication(self, difficulty: str) -> Task:
        """Task: find and merge duplicate records."""
        csv_data = textwrap.dedent("""\
            id,name,email,phone,city
            1,John Smith,john.smith@email.com,555-1234,New York
            2,Jane Doe,jane.doe@email.com,555-2345,Boston
            3,John Smith,j.smith@email.com,555-1234,New York
            4,Robert Brown,robert.brown@email.com,555-3456,Chicago
            5,Jane Doe,jane.doe@email.com,555-9999,Boston
            6,Alice Johnson,alice.j@email.com,555-4567,Denver
            7,Bob Brown,robert.brown@email.com,555-3456,Chicago
            8,Alice Johnson,alice.johnson@email.com,555-4567,Denver
            9,Mike Wilson,mike.w@email.com,555-5678,Seattle
            10,John Smith,john.smith@email.com,555-1234,NYC
        """)

        return Task(
            category=TaskCategory.DATA_ANALYSIS,
            title="Detect and merge duplicate contact records",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The contacts.csv file contains duplicate records with slight variations.
                Write a script that:

                1. Identifies duplicate groups (records likely referring to the same person)
                   based on matching name, email, OR phone number
                2. Creates duplicates.json listing each group with the matching record IDs
                   and the match reason (same_name, same_email, same_phone)
                3. Creates deduplicated.csv keeping only one record per person
                   (prefer the record with the most complete/longest data)
                4. Print a summary: "Found X duplicate groups, merged Y records into Z unique contacts"
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={"contacts.csv": csv_data},
            ),
            ground_truth="Duplicate groups: John Smith (ids 1,3,10), Jane Doe (ids 2,5), Robert/Bob Brown (ids 4,7), Alice Johnson (ids 6,8). 6 unique contacts after dedup.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["duplicates.json", "deduplicated.csv"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import csv; r=list(csv.DictReader(open('deduplicated.csv'))); print(f'unique_{len(r)}'); assert len(r)<=7\"",
                     "output_contains": ["unique_"]},
                ]
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.SCRIPT_WRITING,
                Capability.FILE_CREATION,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.DECOMPOSITION,
            ],
            source="data_analysis_generator:deduplication",
            estimated_minutes=10,
        )

    def _schema_validation(self, difficulty: str) -> Task:
        """Task: validate data against a schema and report violations."""
        schema = textwrap.dedent("""\
            {
                "fields": {
                    "order_id": {"type": "integer", "required": true, "unique": true},
                    "customer_email": {"type": "email", "required": true},
                    "amount": {"type": "float", "required": true, "min": 0.01, "max": 99999.99},
                    "currency": {"type": "string", "required": true, "allowed": ["USD", "EUR", "GBP"]},
                    "status": {"type": "string", "required": true, "allowed": ["pending", "completed", "cancelled"]},
                    "created_at": {"type": "datetime", "required": true, "format": "YYYY-MM-DD HH:MM:SS"}
                }
            }
        """)

        data = textwrap.dedent("""\
            order_id,customer_email,amount,currency,status,created_at
            1001,alice@example.com,29.99,USD,completed,2024-01-15 10:30:00
            1002,bob@example,49.50,USD,pending,2024-01-15 11:00:00
            1003,charlie@example.com,-5.00,EUR,completed,2024-01-15 12:00:00
            1004,diana@example.com,100.00,YEN,pending,2024-01-15 13:00:00
            1001,eve@example.com,75.00,USD,completed,2024-01-15 14:00:00
            1006,,200.00,GBP,unknown,Jan 15 2024
            1007,frank@example.com,0.00,USD,completed,2024-01-15 16:00:00
            1008,grace@example.com,50.00,EUR,completed,2024-01-15 17:00:00
        """)

        return Task(
            category=TaskCategory.DATA_ANALYSIS,
            title="Validate data against schema and report violations",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Write a validation script for orders.csv using the rules in schema.json.

                Create validation_report.json with:
                1. "total_rows": number of data rows
                2. "valid_rows": number of rows with zero violations
                3. "violations": list of objects with:
                   - "row": row number (1-indexed, header = row 0)
                   - "field": which field
                   - "value": the actual value
                   - "rule": which rule was violated
                   - "message": human-readable error message

                Rules to check:
                - required: field must not be empty
                - type: integer/float/email/datetime must parse correctly
                - unique: no duplicate values allowed
                - min/max: numeric range check
                - allowed: value must be in the allowed list
                - format: datetime must match the specified format
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "orders.csv": data,
                    "schema.json": schema,
                },
            ),
            ground_truth="Violations: row 2 invalid email, row 3 amount<0, row 4 currency not in allowed, row 5 duplicate order_id, row 6 missing email + invalid status + bad date format, row 7 amount=0 (below min). Valid rows: 2 (rows 1 and 8).",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["validation_report.json"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import json; d=json.load(open('validation_report.json')); assert d['total_rows']==8; assert d['valid_rows']<=3; assert len(d['violations'])>=5; print('validation_ok')\"",
                     "output_contains": ["validation_ok"]},
                ]
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.SCRIPT_WRITING,
                Capability.FILE_CREATION,
                Capability.CONFIG_READING,
                Capability.DECOMPOSITION,
                Capability.MULTI_FILE_REASONING,
            ],
            source="data_analysis_generator:schema_validation",
            estimated_minutes=10,
        )
