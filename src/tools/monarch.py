import json
import os
from datetime import date

from monarchmoney import MonarchMoney

_mm: MonarchMoney | None = None


def _get_mm() -> MonarchMoney:
    global _mm
    if _mm is None:
        token = os.getenv("MONARCH_TOKEN")
        if not token:
            raise RuntimeError("MONARCH_TOKEN environment variable is not set")
        _mm = MonarchMoney()
        _mm._headers["Authorization"] = f"Bearer {token}"
    return _mm


def _dumps(data) -> str:
    return json.dumps(data, default=str)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


async def get_accounts() -> str:
    """Gets all accounts linked to Monarch Money."""
    return _dumps(await _get_mm().get_accounts())


async def get_account_type_options() -> str:
    """Gets all account types and subtypes available in Monarch Money."""
    return _dumps(await _get_mm().get_account_type_options())


async def get_account_holdings(account_id: str) -> str:
    """Gets holdings for a brokerage or investment account."""
    return _dumps(await _get_mm().get_account_holdings(account_id))


async def get_account_history(account_id: str) -> str:
    """Gets daily balance history for an account."""
    return _dumps(await _get_mm().get_account_history(account_id))


async def get_recent_account_balances(start_date: str | None = None) -> str:
    """Gets daily balances for all accounts from start_date (YYYY-MM-DD). Defaults to last 31 days."""
    return _dumps(await _get_mm().get_recent_account_balances(start_date=start_date))


async def get_aggregate_snapshots(
    start_date: str | None = None,
    end_date: str | None = None,
    account_type: str | None = None,
) -> str:
    """Gets daily net value of all accounts, optionally filtered by date range and account type."""
    kwargs = {}
    if start_date:
        kwargs["start_date"] = date.fromisoformat(start_date)
    if end_date:
        kwargs["end_date"] = date.fromisoformat(end_date)
    if account_type:
        kwargs["account_type"] = account_type
    return _dumps(await _get_mm().get_aggregate_snapshots(**kwargs))


async def get_account_snapshots_by_type(start_date: str, timeframe: str) -> str:
    """Gets net value snapshots for all account types. timeframe is 'year' or 'month'."""
    return _dumps(await _get_mm().get_account_snapshots_by_type(start_date, timeframe))


# ---------------------------------------------------------------------------
# Institutions
# ---------------------------------------------------------------------------


async def get_institutions() -> str:
    """Gets institutions linked to Monarch Money."""
    return _dumps(await _get_mm().get_institutions())


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


async def get_transactions(
    limit: int = 100,
    offset: int = 0,
    start_date: str | None = None,
    end_date: str | None = None,
    search: str = "",
    category_ids: list[str] | None = None,
    account_ids: list[str] | None = None,
    tag_ids: list[str] | None = None,
    has_attachments: bool | None = None,
    has_notes: bool | None = None,
    is_split: bool | None = None,
    is_recurring: bool | None = None,
) -> str:
    """Gets transactions. Defaults to last 100. Filter by date, search, category, account, or tags."""
    return _dumps(await _get_mm().get_transactions(
        limit=limit,
        offset=offset,
        start_date=start_date,
        end_date=end_date,
        search=search,
        category_ids=category_ids or [],
        account_ids=account_ids or [],
        tag_ids=tag_ids or [],
        has_attachments=has_attachments,
        has_notes=has_notes,
        is_split=is_split,
        is_recurring=is_recurring,
    ))


async def get_transactions_summary() -> str:
    """Gets a summary of transactions."""
    return _dumps(await _get_mm().get_transactions_summary())


async def get_transaction_details(transaction_id: str) -> str:
    """Gets detailed information for a single transaction."""
    return _dumps(await _get_mm().get_transaction_details(transaction_id))


async def get_transaction_splits(transaction_id: str) -> str:
    """Gets split details for a transaction."""
    return _dumps(await _get_mm().get_transaction_splits(transaction_id))


async def get_transaction_categories() -> str:
    """Gets all transaction categories configured in the account."""
    return _dumps(await _get_mm().get_transaction_categories())


async def get_transaction_category_groups() -> str:
    """Gets all transaction category groups configured in the account."""
    return _dumps(await _get_mm().get_transaction_category_groups())


async def get_transaction_tags() -> str:
    """Gets all tags configured in the account."""
    return _dumps(await _get_mm().get_transaction_tags())


# ---------------------------------------------------------------------------
# Cashflow & Budgets
# ---------------------------------------------------------------------------


async def get_cashflow(
    limit: int = 100,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Gets cashflow data broken down by category and merchant."""
    return _dumps(await _get_mm().get_cashflow(limit=limit, start_date=start_date, end_date=end_date))


async def get_cashflow_summary(
    limit: int = 100,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Gets cashflow summary: income, expenses, savings, and savings rate."""
    return _dumps(await _get_mm().get_cashflow_summary(limit=limit, start_date=start_date, end_date=end_date))


async def get_budgets(
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Gets budget amounts and actuals. Dates in YYYY-MM-DD format. Defaults to last/next month."""
    return _dumps(await _get_mm().get_budgets(start_date=start_date, end_date=end_date))


# ---------------------------------------------------------------------------
# Recurring transactions
# ---------------------------------------------------------------------------


async def get_recurring_transactions(
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Gets upcoming recurring transactions including merchant and account details."""
    return _dumps(await _get_mm().get_recurring_transactions(start_date=start_date, end_date=end_date))


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


async def get_credit_history() -> str:
    """Gets credit score history and related user details."""
    return _dumps(await _get_mm().get_credit_history())


async def get_subscription_details() -> str:
    """Gets the subscription type for the Monarch Money account."""
    return _dumps(await _get_mm().get_subscription_details())


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_accounts",
            "description": "Gets all accounts linked to Monarch Money.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_type_options",
            "description": "Gets all account types and subtypes available in Monarch Money.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_holdings",
            "description": "Gets holdings for a brokerage or investment account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The account ID to fetch holdings for."},
                },
                "required": ["account_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_history",
            "description": "Gets daily balance history for an account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string", "description": "The account ID to fetch history for."},
                },
                "required": ["account_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_account_balances",
            "description": "Gets daily balances for all accounts. Defaults to the last 31 days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format. Defaults to 31 days ago."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_aggregate_snapshots",
            "description": "Gets daily net value of all accounts, optionally filtered by date range and account type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format."},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format."},
                    "account_type": {"type": "string", "description": "Filter by account type."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_snapshots_by_type",
            "description": "Gets net value snapshots grouped by account type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format."},
                    "timeframe": {"type": "string", "enum": ["year", "month"], "description": "Granularity of snapshots."},
                },
                "required": ["start_date", "timeframe"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_institutions",
            "description": "Gets institutions linked to Monarch Money.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transactions",
            "description": "Gets transactions. Defaults to the last 100. Supports filtering by date, search text, category, account, and tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max transactions to return. Defaults to 100."},
                    "offset": {"type": "integer", "description": "Number of transactions to skip. Defaults to 0."},
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format."},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format."},
                    "search": {"type": "string", "description": "Text to search transactions by."},
                    "category_ids": {"type": "array", "items": {"type": "string"}, "description": "Filter by category IDs."},
                    "account_ids": {"type": "array", "items": {"type": "string"}, "description": "Filter by account IDs."},
                    "tag_ids": {"type": "array", "items": {"type": "string"}, "description": "Filter by tag IDs."},
                    "has_attachments": {"type": "boolean", "description": "Filter by whether transactions have attachments."},
                    "has_notes": {"type": "boolean", "description": "Filter by whether transactions have notes."},
                    "is_split": {"type": "boolean", "description": "Filter by whether transactions are split."},
                    "is_recurring": {"type": "boolean", "description": "Filter by whether transactions are recurring."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transactions_summary",
            "description": "Gets a high-level summary of transactions.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction_details",
            "description": "Gets detailed information for a single transaction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string", "description": "The transaction ID to fetch."},
                },
                "required": ["transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction_splits",
            "description": "Gets split details for a transaction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "string", "description": "The transaction ID to fetch splits for."},
                },
                "required": ["transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction_categories",
            "description": "Gets all transaction categories configured in the account.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction_category_groups",
            "description": "Gets all transaction category groups configured in the account.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction_tags",
            "description": "Gets all tags configured in the account.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cashflow",
            "description": "Gets cashflow data broken down by category and merchant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max records to return. Defaults to 100."},
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format."},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cashflow_summary",
            "description": "Gets cashflow summary including income, expenses, savings, and savings rate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max records to return. Defaults to 100."},
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format."},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_budgets",
            "description": "Gets budget amounts and actuals. Defaults to last and next month.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format."},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recurring_transactions",
            "description": "Gets upcoming recurring transactions including merchant and account details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format."},
                    "end_date": {"type": "string", "description": "End date in YYYY-MM-DD format."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_credit_history",
            "description": "Gets credit score history and related user details.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_subscription_details",
            "description": "Gets the Monarch Money subscription type (trial or paid).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

TOOL_MAPPING = {
    "get_accounts": get_accounts,
    "get_account_type_options": get_account_type_options,
    "get_account_holdings": get_account_holdings,
    "get_account_history": get_account_history,
    "get_recent_account_balances": get_recent_account_balances,
    "get_aggregate_snapshots": get_aggregate_snapshots,
    "get_account_snapshots_by_type": get_account_snapshots_by_type,
    "get_institutions": get_institutions,
    "get_transactions": get_transactions,
    "get_transactions_summary": get_transactions_summary,
    "get_transaction_details": get_transaction_details,
    "get_transaction_splits": get_transaction_splits,
    "get_transaction_categories": get_transaction_categories,
    "get_transaction_category_groups": get_transaction_category_groups,
    "get_transaction_tags": get_transaction_tags,
    "get_cashflow": get_cashflow,
    "get_cashflow_summary": get_cashflow_summary,
    "get_budgets": get_budgets,
    "get_recurring_transactions": get_recurring_transactions,
    "get_credit_history": get_credit_history,
    "get_subscription_details": get_subscription_details,
}
