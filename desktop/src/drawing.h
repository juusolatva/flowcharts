#pragma once

#include <QBrush>
#include <QFont>
#include <QJsonObject>
#include <QPainterPath>
#include <QPen>
#include <QVector>

namespace flowcharts {

struct Primitive {
    QPainterPath path;
    QPen pen{Qt::black};
    QBrush brush{Qt::NoBrush};
    QString text;
    QPointF position;
    QFont font;
    qreal textWidth = 0;
    bool isText = false;
};

struct Drawing {
    QVector<Primitive> primitives;
    QPainterPath hitShape;
    QRectF bounds;
};

// Decode the Graphviz xdot drawing operations emitted by this project's DOT backends.
// Unsupported operations fail explicitly instead of silently dropping parts of a chart.
bool parseDrawing(const QJsonObject &object, Drawing &drawing, QString &error);

} // namespace flowcharts
