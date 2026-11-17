#include "sourceview.h"

#include <QFontDatabase>
#include <QMouseEvent>
#include <QPainter>
#include <QTextBlock>

namespace flowcharts {
namespace {
class Gutter : public QWidget {
public:
    explicit Gutter(SourceView *view) : QWidget(view), m_view(view) {}
    void paintEvent(QPaintEvent *event) override { m_view->paintGutter(event); }

private:
    SourceView *m_view;
};
} // namespace

SourceView::SourceView(QWidget *parent) : QPlainTextEdit(parent), m_gutter(new Gutter(this)) {
    setReadOnly(true);
    setLineWrapMode(NoWrap);
    setFont(QFontDatabase::systemFont(QFontDatabase::FixedFont));
    setTabStopDistance(fontMetrics().horizontalAdvance(' ') * 4);
    setAccessibleName("Source code");
    connect(this, &QPlainTextEdit::blockCountChanged, this, &SourceView::updateGutter);
    connect(this, &QPlainTextEdit::updateRequest, this, [this](const QRect &rect, int dy) {
        if (dy)
            m_gutter->scroll(0, dy);
        else
            m_gutter->update(0, rect.y(), m_gutter->width(), rect.height());
        if (rect.contains(viewport()->rect()))
            updateGutter();
    });
    updateGutter();
}

int SourceView::gutterWidth() const {
    return 16 + fontMetrics().horizontalAdvance('9') * QString::number(blockCount()).size();
}

void SourceView::updateGutter() {
    const auto width = gutterWidth();
    setViewportMargins(width, 0, 0, 0);
    m_gutter->setGeometry(contentsRect().left(), contentsRect().top(), width,
                          contentsRect().height());
}

void SourceView::resizeEvent(QResizeEvent *event) {
    QPlainTextEdit::resizeEvent(event);
    updateGutter();
}

void SourceView::paintGutter(const QPaintEvent *event) {
    QPainter painter(m_gutter);
    painter.fillRect(event->rect(), palette().alternateBase());
    painter.setPen(palette().color(QPalette::PlaceholderText));
    auto block = firstVisibleBlock();
    int top = qRound(blockBoundingGeometry(block).translated(contentOffset()).top());
    while (block.isValid() && top <= event->rect().bottom()) {
        const int height = qRound(blockBoundingRect(block).height());
        if (block.isVisible() && top + height >= event->rect().top())
            painter.drawText(0, top, m_gutter->width() - 7, fontMetrics().height(), Qt::AlignRight,
                             QString::number(block.blockNumber() + 1));
        top += height;
        block = block.next();
    }
}

void SourceView::highlightLines(int first, int last) {
    QList<QTextEdit::ExtraSelection> selections;
    if (first > 0 && first <= blockCount() && last >= first) {
        auto color = palette().color(QPalette::Highlight);
        color.setAlpha(55);
        for (int line = first; line <= qMin(last, blockCount()); ++line) {
            QTextEdit::ExtraSelection selection;
            selection.cursor = QTextCursor(document()->findBlockByNumber(line - 1));
            selection.format.setBackground(color);
            selection.format.setProperty(QTextFormat::FullWidthSelection, true);
            selections.append(selection);
        }
        setTextCursor(QTextCursor(document()->findBlockByNumber(first - 1)));
        ensureCursorVisible();
    }
    setExtraSelections(selections);
}

void SourceView::mouseReleaseEvent(QMouseEvent *event) {
    QPlainTextEdit::mouseReleaseEvent(event);
    if (event->button() == Qt::LeftButton && !textCursor().hasSelection())
        emit lineClicked(cursorForPosition(event->pos()).blockNumber() + 1);
}

} // namespace flowcharts
