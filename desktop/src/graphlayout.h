#pragma once

#include "drawing.h"

namespace flowcharts {

struct GraphNode {
    QString id;
    Drawing drawing;
};
struct GraphLayout {
    QRectF bounds;
    QVector<GraphNode> nodes;
    QVector<Drawing> edges;
    QVector<Drawing> decorations;
};

bool parseLayout(const QJsonObject &json, GraphLayout &graph, QString &error);

} // namespace flowcharts
