#include "graphlayout.h"

#include <QJsonArray>
#include <QSet>
#include <cmath>

namespace flowcharts {

bool parseLayout(const QJsonObject &json, GraphLayout &graph, QString &error) {
    const auto parts = json["bb"].toString().split(',');
    QVector<qreal> bb;
    for (const auto &part : parts) {
        bool ok = false;
        const qreal coordinate = part.toDouble(&ok);
        if (!ok || !std::isfinite(coordinate) || qAbs(coordinate) > 1e9)
            break;
        bb.append(coordinate);
    }
    if (bb.size() != 4 || bb[2] < bb[0] || bb[3] < bb[1]) {
        error = "Invalid Graphviz bounding box";
        return false;
    }
    GraphLayout parsed;
    parsed.bounds = QRectF(bb[0], -bb[3], bb[2] - bb[0], bb[3] - bb[1]);
    QSet<QString> names;
    const int clusters = json["_subgraph_cnt"].toInt();
    const auto objects = json["objects"].toArray();
    for (int i = 0; i < objects.size(); ++i) {
        const auto object = objects[i].toObject();
        Drawing drawing;
        if (!parseDrawing(object, drawing, error))
            return false;
        if (i < clusters) {
            parsed.decorations.append(drawing);
        } else {
            const auto name = object["name"].toString();
            if (name.isEmpty() || names.contains(name)) {
                error = "Invalid or duplicate node name in Graphviz layout";
                return false;
            }
            names.insert(name);
            parsed.nodes.append({name, drawing});
        }
    }
    for (const auto &value : json["edges"].toArray()) {
        Drawing drawing;
        if (!parseDrawing(value.toObject(), drawing, error))
            return false;
        parsed.edges.append(drawing);
    }
    graph = std::move(parsed);
    return true;
}

} // namespace flowcharts
