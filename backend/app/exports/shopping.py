"""The shopping list as an email: plain text and simple HTML that works in mail clients."""

from html import escape

from app.exports.data import NOTICE, ExportData


def shopping_text(data: ExportData, message: str | None = None) -> str:
    lines = [f"Tile shopping list: {data.project_name}", ""]
    if message:
        lines += [message, ""]
    section = None
    for line in data.shopping_lines:
        if line.section != section:
            if section is not None:
                lines.append("")
            section = line.section
            lines.append(f"{section}:")
        lines.append(f"- {line.size} {line.name}: {line.quantity} ({line.detail})")
    lines += ["", NOTICE]
    return "\n".join(lines)


def shopping_html(data: ExportData, sender: str, message: str | None = None) -> str:
    cell = "padding:8px 12px;border-bottom:1px solid #e2e8f0"
    rows = []
    section = None
    for line in data.shopping_lines:
        if line.section != section:
            section = line.section
            rows.append(
                f'<tr><td colspan="2" style="padding:12px 12px 4px;color:#64748b;font-size:12px;'
                f'text-transform:uppercase;letter-spacing:.04em">{escape(section)}</td></tr>'
            )
        rows.append(
            "<tr>"
            f'<td style="{cell}"><strong>{escape(line.size)}</strong><br>'
            f'<span style="color:#64748b">{escape(line.name)}</span></td>'
            f'<td style="{cell};text-align:right"><strong>{escape(line.quantity)}</strong><br>'
            f'<span style="color:#64748b">{escape(line.detail)}</span></td>'
            "</tr>"
        )
    note = (
        f'<p style="margin:0 0 16px;white-space:pre-line">{escape(message)}</p>' if message else ""
    )
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f8fafc;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
<div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:24px">
<div style="height:4px;margin:-24px -24px 20px;border-radius:12px 12px 0 0;background:linear-gradient(135deg,#023b77,#039583)"></div>
<h1 style="margin:0 0 4px;font-size:20px;color:#023b77">Tile shopping list</h1>
<p style="margin:0 0 16px;color:#64748b">{escape(data.project_name)} · sent by {escape(sender)}</p>
{note}
<table style="width:100%;border-collapse:collapse;font-size:14px">
<tbody>{"".join(rows)}</tbody>
</table>
<p style="margin:16px 0 0;padding:10px 12px;background:#fffbeb;color:#92400e;border-radius:8px;font-size:13px">{escape(NOTICE)}</p>
</div></body></html>"""
