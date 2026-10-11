import json
import re
from datetime import datetime

from app.services.llm_service import LLMService


class ContradictionDetector:

    # ============================================================
    # ALLOWED ATTRIBUTES
    # ============================================================

    ALLOWED_ATTRIBUTES = {
        "person",
        "date",
        "time",
        "location",
        "amount",
        "duration",
        "action",
        "event",
        "transaction",
        "sequence",
        "relationship",
    }

    # ============================================================
    # INVALID / UNKNOWN VALUES
    # ============================================================

    INVALID_VALUES = {
        "",
        "unknown",
        "not known",
        "not specified",
        "unspecified",
        "n/a",
        "na",
        "none",
        "null",
        "not available",
        "not mentioned",
        "not stated",
        "cannot be determined",
    }

    # ============================================================
    # INITIALIZATION
    # ============================================================

    def __init__(self):
        self.llm_service = LLMService()

    # ============================================================
    # MAIN ANALYSIS
    # ============================================================

    def analyze(self, statements: list[dict]) -> str:

        # --------------------------------------------------------
        # Validate input
        # --------------------------------------------------------

        if not isinstance(statements, list):
            raise ValueError(
                "Statements must be provided as a list."
            )

        if not statements:
            raise ValueError(
                "At least one statement is required."
            )

        all_claims = []

        # --------------------------------------------------------
        # Extract claims from every statement
        # --------------------------------------------------------

        for index, statement in enumerate(statements):

            if not isinstance(statement, dict):
                continue

            # Support multiple possible input formats
            statement_id = (
                statement.get("statement_id")
                or statement.get("id")
                or f"S{index + 1}"
            )

            statement_text = (
                statement.get("statement")
                or statement.get("text")
                or statement.get("content")
            )

            if not isinstance(statement_text, str):
                continue

            if not statement_text.strip():
                continue

            print(
                f"\nExtracting claims from {statement_id}..."
            )

            claims = self._extract_claims(
                statement_id,
                statement_text
            )

            print(
                f"Extracted {len(claims)} claim(s) "
                f"from {statement_id}."
            )

            # Uncomment these two lines if you want to see
            # exactly what the LLM extracted.
            #
            # for claim in claims:
            #     print("   ", claim)

            all_claims.extend(claims)

        # --------------------------------------------------------
        # Normalize claims
        # --------------------------------------------------------

        normalized_claims = []

        for claim in all_claims:

            normalized_claim = self._normalize_claim(
                claim
            )

            if normalized_claim is None:
                continue

            normalized_claims.append(
                normalized_claim
            )

        # --------------------------------------------------------
        # Remove duplicate claims
        # --------------------------------------------------------

        unique_claims = []
        seen = set()

        for claim in normalized_claims:

            key = (
                claim["statement_id"],
                claim["subject"],
                claim["attribute"],
                claim["value"],
            )

            if key in seen:
                continue

            seen.add(key)
            unique_claims.append(claim)

        normalized_claims = unique_claims

        # --------------------------------------------------------
        # Group claims by subject + attribute
        # --------------------------------------------------------

        groups = {}

        for claim in normalized_claims:

            key = (
                claim["subject"],
                claim["attribute"]
            )

            if key not in groups:
                groups[key] = []

            groups[key].append(claim)

        # --------------------------------------------------------
        # Compare claims
        # --------------------------------------------------------

        findings = []

        for (subject, attribute), claims in groups.items():

            value_groups = {}

            for claim in claims:

                value = claim["value"]

                if value not in value_groups:
                    value_groups[value] = []

                if (
                    claim["statement_id"]
                    not in value_groups[value]
                ):
                    value_groups[value].append(
                        claim["statement_id"]
                    )

            # ----------------------------------------------------
            # More than one distinct value
            # ----------------------------------------------------

            if len(value_groups) > 1:

                values = []

                for value, statement_ids in value_groups.items():

                    values.append({
                        "value": value,
                        "statements": statement_ids
                    })

                findings.append({
                    "type": attribute,
                    "subject": subject,
                    "values": values
                })

        # --------------------------------------------------------
        # Overall result
        # --------------------------------------------------------

        if findings:

            overall_result = (
                "CONFIRMED CONTRADICTION"
            )

        else:

            overall_result = (
                "NO CONTRADICTION FOUND"
            )

        result = {
            "overall_result": overall_result,
            "findings": findings,
            "claims": normalized_claims
        }

        return json.dumps(
            result,
            indent=2
        )

    # ============================================================
    # CLAIM EXTRACTION
    # ============================================================

    def _extract_claims(
        self,
        statement_id: str,
        statement_text: str
    ) -> list[dict]:

        prompt = f"""
You are a factual information extraction system.

Your task is to extract ALL explicit factual claims from the
statement below.

Do not summarize.
Do not interpret.
Do not infer.
Do not invent.
Do not omit explicit facts.

==================================================
STATEMENT ID
==================================================

{statement_id}

==================================================
STATEMENT
==================================================

{statement_text}

==================================================
OUTPUT FORMAT
==================================================

Return ONLY a valid JSON array.

Each claim MUST have exactly these fields:

{{
    "statement_id": "{statement_id}",
    "subject": "meeting",
    "attribute": "location",
    "value": "exact factual value"
}}

Allowed attributes:

person
date
time
location
amount
duration
action
event
transaction
sequence
relationship

==================================================
IMPORTANT EXTRACTION RULES
==================================================

1. Extract EVERY explicit factual attribute that appears
   in the statement.

2. Do NOT stop after extracting one claim.

3. A single statement may contain multiple claims.

For example:

"The witness met the accused at a coffee shop in Thimphu
on 5 September 2026. The meeting lasted approximately
one hour."

You MUST extract ALL THREE:

location:
"coffee shop in Thimphu"

date:
"5 September 2026"

duration:
"approximately one hour"

4. For LOCATION:

Copy the COMPLETE specific location phrase.

If the statement says:

"coffee shop in Thimphu"

output:

"coffee shop in Thimphu"

NOT:

"Thimphu"

If the statement says:

"restaurant in Thimphu"

output:

"restaurant in Thimphu"

NOT:

"Thimphu"

5. For DATE:

Copy the date exactly as written.

Example:

"5 September 2026"

must be:

"5 September 2026"

6. For DURATION:

Copy the duration exactly as written.

Example:

"approximately one hour"

must be:

"approximately one hour"

7. Do NOT create a time claim unless an actual time
   is explicitly stated.

For example:

"at 3:30 PM"

is a time claim.

But:

"on 5 September 2026"

is NOT a time claim.

8. For meeting-related facts, use:

"meeting"

as the subject.

9. Do NOT create artificial subjects such as:

"person 1"
"person 2"
"location"
"date"
"duration"

10. Every value MUST be directly supported by the statement.

11. Never invent information.

12. Never use information outside the statement.

13. Do NOT output:

Unknown
N/A
Not specified
Not mentioned
Not stated

14. If an attribute is not present in the statement,
    simply do not create a claim for that attribute.

15. The statement_id MUST be exactly:

{statement_id}

==================================================
EXAMPLE
==================================================

Statement:

"The witness met the accused at a coffee shop in Thimphu
on 5 September 2026. The meeting lasted approximately
one hour."

Correct output:

[
    {{
        "statement_id": "{statement_id}",
        "subject": "meeting",
        "attribute": "location",
        "value": "coffee shop in Thimphu"
    }},
    {{
        "statement_id": "{statement_id}",
        "subject": "meeting",
        "attribute": "date",
        "value": "5 September 2026"
    }},
    {{
        "statement_id": "{statement_id}",
        "subject": "meeting",
        "attribute": "duration",
        "value": "approximately one hour"
    }}
]

==================================================
FINAL CHECK
==================================================

Before returning the JSON:

- Did you extract ALL explicit facts?
- Did you extract the location?
- Did you extract the date if present?
- Did you extract the duration if present?
- Did you preserve the original wording?
- Did you avoid inventing facts?
- Did you return ONLY valid JSON?

Return ONLY the JSON array.
"""

        # --------------------------------------------------------
        # First extraction attempt
        # --------------------------------------------------------

        claims = self._run_extraction(
            prompt,
            statement_id
        )

        # --------------------------------------------------------
        # If successful, return immediately
        # --------------------------------------------------------

        if claims:
            return claims

        # --------------------------------------------------------
        # Retry only when first extraction fails
        # --------------------------------------------------------

        print(
            f"Retrying claim extraction for {statement_id}..."
        )

        retry_prompt = f"""
Extract ALL factual information from this statement.

Statement ID:
{statement_id}

Statement:
{statement_text}

Return ONLY a valid JSON array.

IMPORTANT:

Extract EVERY explicit fact.

If the statement contains:

"coffee shop in Thimphu"
"5 September 2026"
"approximately one hour"

you MUST return THREE claims:

1. location = "coffee shop in Thimphu"

2. date = "5 September 2026"

3. duration = "approximately one hour"

For locations, preserve the complete phrase.

For dates, copy the original date exactly.

For durations, copy the original duration exactly.

Do not convert dates or durations.

Do not invent information.

Do not output:

Unknown
N/A
Not specified
Not mentioned
Not stated

For meeting-related information:

subject = "meeting"

Allowed attributes:

person
date
time
location
amount
duration
action
event
transaction
sequence
relationship

Statement ID must be exactly:

{statement_id}

Return ONLY valid JSON.
"""

        claims = self._run_extraction(
            retry_prompt,
            statement_id
        )

        return claims

    # ============================================================
    # RUN LLM EXTRACTION
    # ============================================================

    def _run_extraction(
        self,
        prompt: str,
        statement_id: str
    ) -> list[dict]:

        try:

            response = self.llm_service.generate(
                prompt
            )

            response = response.strip()

            # --------------------------------------------------------
            # Remove markdown code fences
            # --------------------------------------------------------

            response = re.sub(
                r"^```(?:json)?\s*",
                "",
                response,
                flags=re.IGNORECASE
            )

            response = re.sub(
                r"\s*```$",
                "",
                response
            )

            response = response.strip()

            # --------------------------------------------------------
            # Extract JSON array if the model added extra text
            # --------------------------------------------------------

            start = response.find("[")
            end = response.rfind("]")

            if start == -1 or end == -1 or end <= start:
                print(
                    f"No JSON array found for {statement_id}."
                )
                return []

            json_text = response[start:end + 1]

            # --------------------------------------------------------
            # Parse JSON
            # --------------------------------------------------------

            data = json.loads(json_text)

            if not isinstance(data, list):
                return []

            valid_claims = []

            # --------------------------------------------------------
            # Validate every claim
            # --------------------------------------------------------

            for claim in data:

                if not isinstance(claim, dict):
                    continue

                claim_statement_id = claim.get(
                    "statement_id"
                )

                subject = claim.get(
                    "subject"
                )

                attribute = claim.get(
                    "attribute"
                )

                value = claim.get(
                    "value"
                )

                # ----------------------------------------------------
                # Statement ID
                # ----------------------------------------------------

                if claim_statement_id != statement_id:
                    continue

                # ----------------------------------------------------
                # Data types
                # ----------------------------------------------------

                if not isinstance(subject, str):
                    continue

                if not isinstance(attribute, str):
                    continue

                if not isinstance(value, str):
                    continue

                subject = subject.strip()

                attribute = (
                    attribute
                    .strip()
                    .lower()
                )

                value = value.strip()

                # ----------------------------------------------------
                # Empty values
                # ----------------------------------------------------

                if not subject:
                    continue

                if not value:
                    continue

                # ----------------------------------------------------
                # Allowed attributes
                # ----------------------------------------------------

                if attribute not in self.ALLOWED_ATTRIBUTES:
                    continue

                # ----------------------------------------------------
                # Remove placeholder values
                # ----------------------------------------------------

                if self._is_invalid_value(value):
                    continue

                # ----------------------------------------------------
                # Store valid claim
                # ----------------------------------------------------

                valid_claims.append({
                    "statement_id": statement_id,
                    "subject": subject,
                    "attribute": attribute,
                    "value": value,
                    "clear": True
                })

            return valid_claims

        except json.JSONDecodeError as e:

            print(
                f"Claim extraction JSON error for "
                f"{statement_id}: {e}"
            )

            return []

        except Exception as e:

            print(
                f"Claim extraction error for "
                f"{statement_id}: {e}"
            )

            return []

    # ============================================================
    # CLAIM NORMALIZATION
    # ============================================================

    def _normalize_claim(
        self,
        claim: dict
    ) -> dict | None:

        subject = self._normalize_subject(
            claim["subject"]
        )

        attribute = (
            claim["attribute"]
            .strip()
            .lower()
        )

        value = claim["value"].strip()

        # --------------------------------------------------------
        # Remove invalid values
        # --------------------------------------------------------

        if self._is_invalid_value(value):
            return None

        # --------------------------------------------------------
        # Attribute-specific normalization
        # --------------------------------------------------------

        if attribute == "date":

            value = self._normalize_date(
                value
            )

        elif attribute == "duration":

            value = self._normalize_duration(
                value
            )

        elif attribute == "amount":

            value = self._normalize_amount(
                value
            )

        else:

            value = self._normalize_text(
                value
            )

        # --------------------------------------------------------
        # Final validation
        # --------------------------------------------------------

        if not value:
            return None

        if self._is_invalid_value(value):
            return None

        return {
            "statement_id": claim["statement_id"],
            "subject": subject,
            "attribute": attribute,
            "value": value,
            "clear": True
        }

    # ============================================================
    # SUBJECT NORMALIZATION
    # ============================================================

    def _normalize_subject(
        self,
        text: str
    ) -> str:

        text = text.lower().strip()

        # Remove leading articles
        text = re.sub(
            r"^(the|a|an)\s+",
            "",
            text
        )

        # Normalize whitespace
        text = re.sub(
            r"\s+",
            " ",
            text
        )

        return text

    # ============================================================
    # TEXT NORMALIZATION
    # ============================================================

    def _normalize_text(
        self,
        text: str
    ) -> str:

        text = text.lower().strip()

        # --------------------------------------------------------
        # Fix common spacing problems
        # --------------------------------------------------------

        text = re.sub(
            r"\s+",
            " ",
            text
        )

        # Example:
        # "coffee shopin Thimphu"
        # becomes:
        # "coffee shop in Thimphu"

        text = re.sub(
            r"\bshopin\b",
            "shop in",
            text
        )

        # --------------------------------------------------------
        # Remove leading articles
        # --------------------------------------------------------

        text = re.sub(
            r"^(a|an|the)\s+",
            "",
            text
        )

        # --------------------------------------------------------
        # Remove trailing punctuation
        # --------------------------------------------------------

        text = text.rstrip(
            ".,;:"
        )

        return text.strip()

    # ============================================================
    # INVALID VALUE CHECK
    # ============================================================

    def _is_invalid_value(
        self,
        value: str
    ) -> bool:

        normalized = self._normalize_text(
            value
        )

        return normalized in self.INVALID_VALUES

    # ============================================================
    # DATE NORMALIZATION
    # ============================================================

    def _normalize_date(
        self,
        value: str
    ) -> str:

        original = value.strip()

        # --------------------------------------------------------
        # Remove ordinal suffixes
        # --------------------------------------------------------

        cleaned = re.sub(
            r"(\d+)(st|nd|rd|th)\b",
            r"\1",
            original,
            flags=re.IGNORECASE
        )

        cleaned = re.sub(
            r"\s+",
            " ",
            cleaned
        ).strip()

        # --------------------------------------------------------
        # Supported formats
        # --------------------------------------------------------

        formats = [
            "%Y-%m-%d",
            "%d-%m-%Y",
            "%d/%m/%Y",
            "%d.%m.%Y",
            "%d %B %Y",
            "%d %b %Y",
            "%B %d %Y",
            "%b %d %Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B, %Y",
            "%d %b, %Y",
        ]

        # --------------------------------------------------------
        # Try cleaned date
        # --------------------------------------------------------

        for date_format in formats:

            try:

                parsed = datetime.strptime(
                    cleaned,
                    date_format
                )

                return parsed.strftime(
                    "%Y-%m-%d"
                )

            except ValueError:
                continue

        # --------------------------------------------------------
        # Try without comma
        # --------------------------------------------------------

        cleaned_no_comma = cleaned.replace(
            ",",
            ""
        )

        for date_format in [
            "%d %B %Y",
            "%d %b %Y",
            "%B %d %Y",
            "%b %d %Y",
        ]:

            try:

                parsed = datetime.strptime(
                    cleaned_no_comma,
                    date_format
                )

                return parsed.strftime(
                    "%Y-%m-%d"
                )

            except ValueError:
                continue

        # --------------------------------------------------------
        # If date cannot be parsed,
        # preserve normalized text
        # --------------------------------------------------------

        return self._normalize_text(
            original
        )

    # ============================================================
    # DURATION NORMALIZATION
    # ============================================================

    def _normalize_duration(
        self,
        value: str
    ) -> str:

        text = value.lower().strip()

        # --------------------------------------------------------
        # Remove approximation words
        # --------------------------------------------------------

        approximation_words = [
            "approximately",
            "approx.",
            "approx",
            "about",
            "around",
            "roughly",
            "nearly",
            "almost",
        ]

        for word in approximation_words:

            text = re.sub(
                rf"\b{re.escape(word)}\b",
                "",
                text
            )

        text = re.sub(
            r"\s+",
            " ",
            text
        ).strip()

        # --------------------------------------------------------
        # Word numbers
        # --------------------------------------------------------

        number_words = {
            "zero": 0,
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
            "eleven": 11,
            "twelve": 12,
            "thirteen": 13,
            "fourteen": 14,
            "fifteen": 15,
            "sixteen": 16,
            "seventeen": 17,
            "eighteen": 18,
            "nineteen": 19,
            "twenty": 20,
            "thirty": 30,
            "forty": 40,
            "fifty": 50,
            "sixty": 60,
        }

        for word, number in number_words.items():

            text = re.sub(
                rf"\b{word}\b",
                str(number),
                text
            )

        # --------------------------------------------------------
        # Hours
        # --------------------------------------------------------

        hour_match = re.fullmatch(
            r"(\d+(?:\.\d+)?)\s*"
            r"(hour|hours|hr|hrs)",
            text
        )

        if hour_match:

            hours = float(
                hour_match.group(1)
            )

            minutes = round(
                hours * 60
            )

            return f"{minutes} minutes"

        # --------------------------------------------------------
        # Minutes
        # --------------------------------------------------------

        minute_match = re.fullmatch(
            r"(\d+(?:\.\d+)?)\s*"
            r"(minute|minutes|min|mins)",
            text
        )

        if minute_match:

            minutes = float(
                minute_match.group(1)
            )

            return (
                f"{round(minutes)} minutes"
            )

        # --------------------------------------------------------
        # Seconds
        # --------------------------------------------------------

        second_match = re.fullmatch(
            r"(\d+(?:\.\d+)?)\s*"
            r"(second|seconds|sec|secs)",
            text
        )

        if second_match:

            seconds = float(
                second_match.group(1)
            )

            return (
                f"{round(seconds)} seconds"
            )

        # --------------------------------------------------------
        # If no conversion was possible
        # --------------------------------------------------------

        return self._normalize_text(
            value
        )

    # ============================================================
    # AMOUNT NORMALIZATION
    # ============================================================

    def _normalize_amount(
        self,
        value: str
    ) -> str:

        text = value.lower().strip()

        # Remove commas from numbers
        text = text.replace(
            ",",
            ""
        )

        # Normalize Bhutanese currency notation
        text = re.sub(
            r"\bnu\.?\b",
            "nu",
            text
        )

        # Normalize whitespace
        text = re.sub(
            r"\s+",
            " ",
            text
        )

        return text.strip()