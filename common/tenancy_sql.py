"""SQL fragment restricting ``(marketplace, account_id)`` rows to one organization.

Shared by the backend services and worker tasks (both have their own ``app``
package, so the helper lives here).
"""

from __future__ import annotations


def account_scope_sql(organization_param: str = "organization_id", alias: str = "") -> str:
    """Server-side bind form: ``{organization_param:String}``."""
    prefix = f"{alias}." if alias else ""
    return (
        f"({prefix}marketplace, {prefix}account_id) IN ("
        "SELECT marketplace, account_id FROM dim_account FINAL"
        f" WHERE organization_id = {{{organization_param}:String}})"
    )
