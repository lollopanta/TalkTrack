"""Render the concept sheet with QtSvg (does not require a browser renderer)."""
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen
from PyQt6.QtSvg import QSvgRenderer


ROOT = Path(__file__).parent
CONCEPTS = [
    (
        "01-double-track.svg",
        "01-double-track-lockup.svg",
        "A · Doppia traccia",
        "Due T affiancate: Talk e Track, con il punto REC dell'icona attuale.",
    ),
    (
        "02-handoff.svg",
        "02-handoff-lockup.svg",
        "B · Passaggio",
        "Due T alternate si passano la conversazione come turni distinti.",
    ),
    (
        "03-record-cursor.svg",
        "03-record-cursor-lockup.svg",
        "C · Cursore REC",
        "Una T diventa cursore di registrazione su una riga di trascrizione.",
    ),
]


def draw_svg(painter, path, rect):
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        raise ValueError(f"Invalid SVG: {path}")
    renderer.render(painter, QRectF(*rect))


def main():
    app = QGuiApplication([])
    width, height = 1600, 960
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#f7f7f4"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    painter.setPen(QColor("#161616"))
    painter.setFont(QFont("Avenir Next", 30, QFont.Weight.Bold))
    painter.drawText(60, 62, "TalkTrack — tre direzioni")
    painter.setPen(QColor("#666666"))
    painter.setFont(QFont("Avenir Next", 14))
    painter.drawText(60, 93, "Bozze in scala di grigi · lockup tipografico esplorativo")

    margin, gap = 60, 26
    card_width = 476
    card_y, card_height = 130, 770
    for index, (mark_name, lockup_name, title, note) in enumerate(CONCEPTS):
        x = margin + index * (card_width + gap)
        painter.setBrush(QColor("#ffffff"))
        painter.setPen(QPen(QColor("#242424" if index == 0 else "#dfdfda"), 2 if index == 0 else 1))
        painter.drawRoundedRect(QRectF(x, card_y, card_width, card_height), 18, 18)

        draw_svg(painter, ROOT / mark_name, (x + 100, card_y + 34, 276, 276))
        draw_svg(painter, ROOT / lockup_name, (x + 42, card_y + 314, 392, 116))

        painter.setPen(QColor("#777777"))
        painter.setFont(QFont("Avenir Next", 10))
        painter.drawText(x + 34, card_y + 465, "LEGGIBILITÀ IN PICCOLO")
        icon_y = card_y + 477
        for size in (64, 32, 16):
            draw_svg(painter, ROOT / mark_name, (x + 38, icon_y, size, size))
            painter.setPen(QColor("#888888"))
            painter.drawText(x + 38, icon_y + 80, f"{size} px")
            x += size + 38
        x = margin + index * (card_width + gap)

        painter.setPen(QColor("#161616"))
        painter.setFont(QFont("Avenir Next", 17, QFont.Weight.Bold))
        painter.drawText(x + 34, card_y + 590, title)
        if index == 0:
            painter.setFont(QFont("Avenir Next", 9, QFont.Weight.Bold))
            painter.drawText(x + 34, card_y + 613, "CONSIGLIATA · CONSERVA L'EQUITY ATTUALE")

        painter.setPen(QColor("#555555"))
        painter.setFont(QFont("Avenir Next", 12))
        lines = []
        words, line = note.split(), ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if len(candidate) > 52 and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        for row, line in enumerate(lines[:3]):
            painter.drawText(x + 34, card_y + 652 + row * 21, line)

    painter.end()
    output = ROOT / "concepts.png"
    if not image.save(str(output)):
        raise RuntimeError(f"Could not save {output}")
    print(output)
    app.quit()


if __name__ == "__main__":
    main()
