"""Render the compact macOS status icon at standard and Retina resolutions."""

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer


RESOURCES = Path(__file__).resolve().parent


def main():
    app = QGuiApplication([])
    renderer = QSvgRenderer(str(RESOURCES / "talktrack-menubar.svg"))
    if not renderer.isValid():
        raise RuntimeError("Invalid TalkTrack menu-bar SVG.")

    for size in (18, 36):
        image = QImage(QSize(size, size), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        image.save(str(RESOURCES / f"talktrack-menubar-{size}.png"))


if __name__ == "__main__":
    main()
