"""Render the fresh concept sheet with QtSvg (no browser renderer needed)."""
from pathlib import Path

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen
from PyQt6.QtSvg import QSvgRenderer


ROOT = Path(__file__).parent
CONCEPTS = [
    (
        "01-confluence-color.svg",
        "01-confluence-color-lockup.svg",
        "A · Confluenza",
        "Due percorsi di conversazione confluiscono in un'unica traccia chiara.",
        ("#3867E8", "#0B877A", "#24344B"),
        "blu · giada · inchiostro",
    ),
    (
        "02-highlight-color.svg",
        "02-highlight-color-lockup.svg",
        "B · Evidenza",
        "Una parentesi editoriale porta in primo piano il passaggio importante.",
        ("#6C45F5", "#E44747"),
        "viola · rosso",
    ),
    (
        "03-index-color.svg",
        "03-index-color-lockup.svg",
        "C · Indice",
        "Tre righe diventano una pagina consultabile con un passaggio marcato.",
        ("#1F6B67", "#CF5949"),
        "petrolio · corallo",
    ),
]

CARD_BACKGROUNDS = ("#F0F4FF", "#F5F0FF", "#EFF7F4")


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
    painter.drawText(60, 62, "TalkTrack — Evidenza aggiornata")
    painter.setPen(QColor("#666666"))
    painter.setFont(QFont("Avenir Next", 14))
    painter.drawText(60, 93, "Il trattino centrale è diventato un cerchio rosso · lettering esplorativo")

    margin, gap = 60, 26
    card_width = 476
    card_y, card_height = 130, 770
    for index, (mark_name, lockup_name, title, note, palette, palette_name) in enumerate(CONCEPTS):
        x = margin + index * (card_width + gap)
        painter.setBrush(QColor(CARD_BACKGROUNDS[index]))
        selected = index == 1
        painter.setPen(QPen(QColor("#242424" if selected else "#dfdfda"), 2 if selected else 1))
        painter.drawRoundedRect(QRectF(x, card_y, card_width, card_height), 18, 18)

        draw_svg(painter, ROOT / mark_name, (x + 100, card_y + 34, 276, 276))
        draw_svg(painter, ROOT / lockup_name, (x + 42, card_y + 314, 392, 116))

        painter.setPen(QColor("#777777"))
        painter.setFont(QFont("Avenir Next", 10))
        painter.drawText(x + 34, card_y + 465, "LEGGIBILITÀ IN PICCOLO")
        icon_y = card_y + 477
        icon_x = x + 38
        for size in (64, 32, 16):
            draw_svg(painter, ROOT / mark_name, (icon_x, icon_y, size, size))
            painter.setPen(QColor("#888888"))
            painter.drawText(icon_x, icon_y + 80, f"{size} px")
            icon_x += size + 38

        painter.setPen(QColor("#161616"))
        painter.setFont(QFont("Avenir Next", 17, QFont.Weight.Bold))
        painter.drawText(x + 34, card_y + 590, title)
        if selected:
            painter.setFont(QFont("Avenir Next", 9, QFont.Weight.Bold))
            painter.drawText(x + 34, card_y + 613, "SCELTA · CERCHIO ROSSO")

        painter.setPen(QColor("#555555"))
        painter.setFont(QFont("Avenir Next", 12))
        lines, words, line = [], note.split(), ""
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

        swatch_x = x + 34
        swatch_y = card_y + 706
        painter.setPen(Qt.PenStyle.NoPen)
        for color in palette:
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(swatch_x, swatch_y, 28, 18), 5, 5)
            swatch_x += 38
        painter.setPen(QColor("#777777"))
        painter.setFont(QFont("Avenir Next", 10))
        painter.drawText(x + 34, card_y + 750, palette_name)

    painter.end()
    output = ROOT / "concepts.png"
    if not image.save(str(output)):
        raise RuntimeError(f"Could not save {output}")
    print(output)
    app.quit()


if __name__ == "__main__":
    main()
