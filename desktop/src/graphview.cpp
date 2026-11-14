#include "graphview.h"

#include <QApplication>
#include <QFontMetricsF>
#include <QGraphicsItem>
#include <QMouseEvent>
#include <QPainter>
#include <QSignalBlocker>
#include <QStyleOptionGraphicsItem>
#include <QWheelEvent>
#include <cmath>

namespace flowcharts {
namespace {

QColor themed(QColor color, const QPalette &palette) {
    if (color.red() < 40 && color.green() < 40 && color.blue() < 40) {
        auto result = palette.color(QPalette::Text);
        result.setAlpha(color.alpha());
        return result;
    }
    return color;
}

class DrawingItem : public QGraphicsItem {
public:
    explicit DrawingItem(const Drawing &drawing, const QString &id = {}) : m_drawing(drawing) {
        setData(0, id);
        if (!id.isEmpty()) {
            setFlag(ItemIsSelectable);
            setCursor(Qt::PointingHandCursor);
            setToolTip(id);
        } else {
            setAcceptedMouseButtons(Qt::NoButton);
        }
    }
    QRectF boundingRect() const override { return m_drawing.bounds.adjusted(-2, -2, 2, 2); }
    QPainterPath shape() const override { return m_drawing.hitShape; }
    void paint(QPainter *painter, const QStyleOptionGraphicsItem *, QWidget *) override {
        const auto palette = QApplication::palette();
        if (!data(0).toString().isEmpty()) {
            painter->setPen(Qt::NoPen);
            painter->setBrush(palette.base());
            painter->drawPath(m_drawing.hitShape);
        }
        if (isSelected()) {
            auto fill = palette.color(QPalette::Highlight);
            fill.setAlpha(45);
            painter->fillPath(m_drawing.hitShape, fill);
        }
        for (const auto &primitive : m_drawing.primitives) {
            painter->save();
            auto pen = primitive.pen;
            pen.setColor(themed(pen.color(), palette));
            painter->setPen(pen);
            auto brush = primitive.brush;
            brush.setColor(themed(brush.color(), palette));
            painter->setBrush(brush);
            if (primitive.isText) {
                painter->setFont(primitive.font);
                const QFontMetricsF metrics(primitive.font);
                const qreal actualWidth = metrics.horizontalAdvance(primitive.text);
                painter->translate(primitive.position);
                // Match Graphviz's text extent even when Qt resolves a different font.
                if (actualWidth > 0 && primitive.textWidth > 0)
                    painter->scale(primitive.textWidth / actualWidth, 1);
                painter->drawText(QPointF(0, 0), primitive.text);
            } else {
                painter->drawPath(primitive.path);
            }
            painter->restore();
        }
        if (isSelected()) {
            painter->setPen(QPen(palette.highlight(), 2));
            painter->setBrush(Qt::NoBrush);
            painter->drawPath(m_drawing.hitShape);
        }
    }

private:
    Drawing m_drawing;
};

} // namespace

GraphView::GraphView(QWidget *parent) : QGraphicsView(parent) {
    setScene(new QGraphicsScene(this));
    setRenderHint(QPainter::Antialiasing);
    setRenderHint(QPainter::TextAntialiasing);
    setDragMode(ScrollHandDrag);
    setTransformationAnchor(AnchorUnderMouse);
    setResizeAnchor(AnchorViewCenter);
    setBackgroundRole(QPalette::Base);
    setFrameShape(QFrame::NoFrame);
    setAccessibleName("Interactive flowchart");
    connect(scene(), &QGraphicsScene::selectionChanged, this,
            [this] { emit nodeSelected(selectedNode()); });
    clearGraph("Open Python files or a folder to get started");
}

void GraphView::setGraph(const GraphLayout &graph, const QString &key) {
    const bool same = key == m_key;
    const auto previousSelection = same ? selectedNode() : QString{};
    const auto center = mapToScene(viewport()->rect().center());
    {
        const QSignalBlocker blocker(scene());
        scene()->clear();
        m_nodes.clear();
        m_key = key;
        m_message = graph.nodes.isEmpty() ? "No charts in this workspace" : QString{};
        for (const auto &drawing : graph.decorations) {
            auto *item = new DrawingItem(drawing);
            item->setZValue(-2);
            scene()->addItem(item);
        }
        for (const auto &drawing : graph.edges) {
            auto *item = new DrawingItem(drawing);
            item->setZValue(-1);
            scene()->addItem(item);
        }
        for (const auto &node : graph.nodes) {
            auto *item = new DrawingItem(node.drawing, node.id);
            scene()->addItem(item);
            m_nodes.insert(node.id, item);
        }
        scene()->setSceneRect(
            graph.bounds.united(scene()->itemsBoundingRect()).adjusted(-30, -30, 30, 30));
        if (same) {
            centerOn(center);
            if (m_nodes.contains(previousSelection))
                m_nodes[previousSelection]->setSelected(true);
        } else {
            fitGraph();
        }
    }
    viewport()->update();
    emit nodeSelected(selectedNode());
}

void GraphView::clearGraph(const QString &message) {
    const QSignalBlocker blocker(scene());
    scene()->clear();
    m_nodes.clear();
    m_key.clear();
    m_message = message;
    resetTransform();
    scene()->setSceneRect(0, 0, 1, 1);
    viewport()->update();
}

QString GraphView::selectedNode() const {
    const auto selected = scene()->selectedItems();
    return selected.isEmpty() ? QString{} : selected.first()->data(0).toString();
}

void GraphView::selectNode(const QString &id) {
    {
        const QSignalBlocker blocker(scene());
        scene()->clearSelection();
        if (auto *item = m_nodes.value(id, nullptr)) {
            item->setSelected(true);
            ensureVisible(item, 40, 40);
        }
    }
    emit nodeSelected(selectedNode());
}

void GraphView::fitGraph() {
    resetTransform();
    fitInView(sceneRect(), Qt::KeepAspectRatio);
    if (transform().m11() > 1.5)
        resetTransform();
}

void GraphView::zoom(qreal factor) {
    const auto scaleFactor = transform().m11() * factor;
    if (std::isfinite(factor) && scaleFactor >= 0.02 && scaleFactor <= 30)
        scale(factor, factor);
}

void GraphView::wheelEvent(QWheelEvent *event) {
    zoom(std::pow(1.0015, event->angleDelta().y()));
    event->accept();
}

void GraphView::mouseDoubleClickEvent(QMouseEvent *event) {
    auto *item = itemAt(event->pos());
    if (item && !item->data(0).toString().isEmpty()) {
        emit nodeActivated(item->data(0).toString());
        event->accept();
        return;
    }
    QGraphicsView::mouseDoubleClickEvent(event);
}

void GraphView::drawForeground(QPainter *painter, const QRectF &) {
    if (m_message.isEmpty())
        return;
    painter->save();
    painter->resetTransform();
    painter->setPen(palette().color(QPalette::Text));
    painter->drawText(viewport()->rect().adjusted(30, 30, -30, -30),
                      Qt::AlignCenter | Qt::TextWordWrap, m_message);
    painter->restore();
}

} // namespace flowcharts
