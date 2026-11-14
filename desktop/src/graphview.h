#pragma once

#include "graphlayout.h"

#include <QGraphicsView>
#include <QHash>

namespace flowcharts {

class GraphView : public QGraphicsView {
    Q_OBJECT
public:
    explicit GraphView(QWidget *parent = nullptr);
    void setGraph(const GraphLayout &graph, const QString &key);
    void clearGraph(const QString &message = {});
    void selectNode(const QString &id);
    QString selectedNode() const;
    QString chartKey() const { return m_key; }
    void fitGraph();
    void zoom(qreal factor);
signals:
    void nodeSelected(const QString &id);
    void nodeActivated(const QString &id);

protected:
    void wheelEvent(QWheelEvent *event) override;
    void mouseDoubleClickEvent(QMouseEvent *event) override;
    void drawForeground(QPainter *painter, const QRectF &rect) override;

private:
    QHash<QString, QGraphicsItem *> m_nodes;
    QString m_key;
    QString m_message;
};

} // namespace flowcharts
