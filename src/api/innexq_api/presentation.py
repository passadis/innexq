"""Deterministic presentation only; no retrieval, arithmetic or authorization."""

from html import escape
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID

from innexq_gateway.pricing import PricingResult


def decision_url(origin: str, run_id: UUID, version: int, brief_hash: str) -> str:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Control Room requires an exact HTTPS origin")
    return (
        origin + "/?" + urlencode({"run": str(run_id), "version": str(version), "hash": brief_hash})
    )


def renewal_email(
    facts: dict[str, str],
    price: PricingResult,
    run_id: UUID,
    version: int,
    filename: str,
    output_folder_url: str,
) -> str:
    """Render final approved bytes; all dynamic text and URLs are escaped."""
    rows = "".join(
        '<tr><td style="padding:10px 0;color:#526476;border-bottom:1px solid #e3e9ef">'
        + escape(label)
        + '</td><td align="right" style="padding:10px 0;font-weight:bold;'
        'border-bottom:1px solid #e3e9ef">' + escape(value) + "</td></tr>"
        for label, value in [
            ("Contract", facts["contract_id"]),
            ("Service", facts["service_level"]),
            ("Renewal term", facts["term_months"] + " months"),
            ("Annual list value", f"{price.currency} {price.annual_value}"),
            ("Discount", f"{price.discount_percent}% ({price.currency} {price.discount_amount})"),
            ("Net annual value", f"{price.currency} {price.discounted_annual_value}"),
        ]
    )
    document = ""
    if output_folder_url:
        url = output_folder_url + "/" + quote(filename, safe="")
        document = (
            '<p style="margin:26px 0"><a style="background:#087f83;color:#ffffff;'
            'padding:14px 22px;text-decoration:none;font-weight:bold;display:inline-block" '
            f'href="{escape(url, quote=True)}">Open renewal document</a></p>'
            '<p style="font-size:13px;color:#526476">SharePoint sign-in and existing '
            "document permissions apply. No public sharing access is granted.</p>"
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;background:#f3f6f9;color:#172d40;'
        'font-family:Segoe UI,Arial,sans-serif">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td align="center" style="padding:24px 12px">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        'style="width:100%;max-width:600px;background:#ffffff">'
        '<tr><td style="padding:24px 28px;background:#112638;color:#ffffff">'
        '<span style="font-size:28px;font-weight:bold">Innex<span '
        'style="color:#64d8d3">Q</span></span>'
        '<p style="margin:8px 0 0;font-size:12px;letter-spacing:2px">CONTRACT RENEWAL</p>'
        '</td></tr><tr><td style="padding:28px">'
        '<p style="color:#8a5700;font-size:12px;font-weight:bold">SYNTHETIC DEMO · TEST EMAIL</p>'
        '<h1 style="font-size:25px;line-height:1.3;margin:12px 0">Your renewal summary</h1>'
        f'<p style="line-height:1.6">The renewal package for <strong>'
        f"{escape(facts['customer_name'])}</strong> is ready for review.</p>"
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse;font-size:14px">'
        + rows
        + "</table>"
        + document
        + '<p style="line-height:1.6">The renewal document contains the full supporting '
        "evidence. This message is a fictional hackathon demonstration, "
        "not a commercial offer or commitment.</p></td></tr>"
        '<tr><td style="padding:20px 28px;background:#edf3f7;font-size:12px;color:#526476">'
        f"InnexQ · Governed enterprise workflows<br>Brief v{version} · Run {run_id}"
        "</td></tr></table></td></tr></table></body></html>"
    )
