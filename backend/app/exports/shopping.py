"""The shopping list as an email: plain text and simple HTML that works in mail clients."""

from html import escape

from app.exports.data import NOTICE, ExportData


def _boxes(n: int) -> str:
    return f"{n} {'box' if n == 1 else 'boxes'}"


def shopping_text(data: ExportData, message: str | None = None) -> str:
    lines = [f"Tile shopping list: {data.project_name}", ""]
    if message:
        lines += [message, ""]
    for item in data.shopping:
        t = item.tile
        lines.append(
            f"- {t.tile.size_label} {t.tile.name}: {_boxes(t.boxes)} "
            f"({t.tiles_bought} tiles, {t.tile.tiles_per_box} per box)"
        )
    total = sum(i.tile.boxes for i in data.shopping)
    lines += ["", f"Total: {_boxes(total)}", "", NOTICE]
    return "\n".join(lines)


def shopping_html(data: ExportData, sender: str, message: str | None = None) -> str:
    rows = "".join(
        "<tr>"
        f'<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0">'
        f"<strong>{escape(i.tile.tile.size_label)}</strong><br>"
        f'<span style="color:#64748b">{escape(i.tile.tile.name)}</span></td>'
        f'<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right">'
        f"<strong>{_boxes(i.tile.boxes)}</strong><br>"
        f'<span style="color:#64748b">{i.tile.tiles_bought} tiles · '
        f"{i.tile.tile.tiles_per_box} per box</span></td>"
        "</tr>"
        for i in data.shopping
    )
    total = sum(i.tile.boxes for i in data.shopping)
    note = (
        f'<p style="margin:0 0 16px;white-space:pre-line">{escape(message)}</p>' if message else ""
    )
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f8fafc;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
<div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:24px">
<h1 style="margin:0 0 4px;font-size:20px">Tile shopping list</h1>
<p style="margin:0 0 16px;color:#64748b">{escape(data.project_name)} · sent by {escape(sender)}</p>
{note}
<table style="width:100%;border-collapse:collapse;font-size:14px">
<tbody>{rows}</tbody>
<tfoot><tr><td style="padding:10px 12px;font-weight:bold">Total</td>
<td style="padding:10px 12px;text-align:right;font-weight:bold">{_boxes(total)}</td></tr></tfoot>
</table>
<p style="margin:16px 0 0;padding:10px 12px;background:#fffbeb;color:#92400e;border-radius:8px;font-size:13px">{escape(NOTICE)}</p>
</div></body></html>"""
