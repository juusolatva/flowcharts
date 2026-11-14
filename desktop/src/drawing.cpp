#include "drawing.h"

#include <QFontMetricsF>
#include <QJsonArray>
#include <cmath>

namespace flowcharts {
namespace {

bool point(const QJsonValue &value, QPointF &result) {
    const auto xy = value.toArray();
    if (xy.size() != 2 || !xy[0].isDouble() || !xy[1].isDouble() ||
        !std::isfinite(xy[0].toDouble()) || !std::isfinite(xy[1].toDouble()))
        return false;
    result = {xy[0].toDouble(), -xy[1].toDouble()};
    return true;
}

QColor color(const QString &text) {
    // Graphviz uses RRGGBBAA; Qt's eight-digit hex format is AARRGGBB.
    if (text.size() == 9 && text.startsWith('#')) {
        bool ok = false;
        const auto rgba = text.mid(1).toUInt(&ok, 16);
        if (ok)
            return QColor((rgba >> 24) & 255, (rgba >> 16) & 255, (rgba >> 8) & 255, rgba & 255);
    }
    return QColor(text);
}

bool geometry(const QJsonObject &op, QPainterPath &path) {
    const auto kind = op["op"].toString();
    if (kind == "e" || kind == "E") {
        const auto rect = op["rect"].toArray();
        if (rect.size() != 4)
            return false;
        for (const auto &v : rect) {
            if (!v.isDouble() || !std::isfinite(v.toDouble()))
                return false;
        }
        const qreal rx = rect[2].toDouble(), ry = rect[3].toDouble();
        if (rx < 0 || ry < 0)
            return false;
        path.addEllipse(QRectF(rect[0].toDouble() - rx, -rect[1].toDouble() - ry, 2 * rx, 2 * ry));
        return true;
    }
    const auto points = op["points"].toArray();
    if (points.isEmpty())
        return false;
    QVector<QPointF> vertices;
    for (const auto &v : points) {
        QPointF p;
        if (!point(v, p))
            return false;
        vertices.append(p);
    }
    path.moveTo(vertices[0]);
    if (kind == "b" || kind == "B") {
        if ((vertices.size() - 1) % 3 != 0)
            return false;
        for (qsizetype i = 1; i + 2 < vertices.size(); i += 3)
            path.cubicTo(vertices[i], vertices[i + 1], vertices[i + 2]);
    } else {
        for (qsizetype i = 1; i < vertices.size(); ++i)
            path.lineTo(vertices[i]);
        if (kind == "p" || kind == "P")
            path.closeSubpath();
    }
    return true;
}

bool operations(const QJsonArray &ops, Drawing &drawing, bool selectable, QString &error) {
    QPen pen(Qt::black);
    QColor fill(Qt::black);
    QFont font("Helvetica");
    font.setPixelSize(14);
    for (const auto &value : ops) {
        const auto op = value.toObject();
        const auto kind = op["op"].toString();
        if (kind == "c" || kind == "C") {
            const auto c = color(op["color"].toString());
            if (!c.isValid()) {
                error = "Unsupported Graphviz color or gradient";
                return false;
            }
            if (kind == "c")
                pen.setColor(c);
            else
                fill = c;
        } else if (kind == "F") {
            const auto size = op["size"].toDouble();
            if (!std::isfinite(size) || size < 1 || size > 10000) {
                error = "Invalid Graphviz font size";
                return false;
            }
            font.setFamily(op["face"].toString());
            font.setPixelSize(qRound(size));
        } else if (kind == "t") {
            const int flags = op["fontchar"].toInt();
            font.setBold((flags & 1) != 0);
            font.setItalic((flags & 2) != 0);
            font.setUnderline((flags & 4) != 0);
            font.setStrikeOut((flags & 32) != 0);
        } else if (kind == "S") {
            const auto style = op["style"].toString();
            if (style == "dashed")
                pen.setStyle(Qt::DashLine);
            else if (style == "dotted")
                pen.setStyle(Qt::DotLine);
            else if (style == "solid")
                pen.setStyle(Qt::SolidLine);
            else if (style == "bold")
                pen.setWidthF(2);
            else if (style.startsWith("setlinewidth(") && style.endsWith(')')) {
                bool ok = false;
                const auto width = style.mid(13, style.size() - 14).toDouble(&ok);
                if (!ok || !std::isfinite(width) || width < 0 || width > 10000) {
                    error = "Invalid Graphviz line width";
                    return false;
                }
                pen.setWidthF(width);
            } else {
                error = "Unsupported Graphviz line style: " + style;
                return false;
            }
        } else if (kind == "T") {
            Primitive primitive;
            primitive.isText = true;
            primitive.text = op["text"].toString();
            primitive.font = font;
            primitive.pen = pen;
            primitive.textWidth = op["width"].toDouble();
            if (!point(op["pt"], primitive.position) || !std::isfinite(primitive.textWidth) ||
                primitive.textWidth < 0) {
                error = "Invalid Graphviz text geometry";
                return false;
            }
            const auto align = op["align"].toString();
            if (align == "c")
                primitive.position.rx() -= primitive.textWidth / 2;
            else if (align == "r")
                primitive.position.rx() -= primitive.textWidth;
            const QFontMetricsF metrics(font);
            drawing.bounds |=
                QRectF(primitive.position.x(), primitive.position.y() - metrics.ascent(),
                       primitive.textWidth, metrics.height());
            drawing.primitives.append(primitive);
        } else if (kind == "e" || kind == "E" || kind == "p" || kind == "P" || kind == "b" ||
                   kind == "B" || kind == "L") {
            Primitive primitive;
            primitive.pen = pen;
            if (kind == "E" || kind == "P" || kind == "B")
                primitive.brush = fill;
            if (!geometry(op, primitive.path)) {
                error = "Invalid Graphviz path geometry";
                return false;
            }
            drawing.bounds |= primitive.path.boundingRect().adjusted(-3, -3, 3, 3);
            if (selectable)
                drawing.hitShape.addPath(primitive.path);
            drawing.primitives.append(primitive);
        } else {
            error = "Unsupported Graphviz drawing operation: " + kind;
            return false;
        }
    }
    return true;
}

} // namespace

bool parseDrawing(const QJsonObject &object, Drawing &drawing, QString &error) {
    for (const auto *key : {"_draw_", "_ldraw_", "_hdraw_", "_tdraw_", "_hldraw_", "_tldraw_"}) {
        if (!operations(object[key].toArray(), drawing, QByteArray(key) == "_draw_", error))
            return false;
    }
    return true;
}

} // namespace flowcharts
