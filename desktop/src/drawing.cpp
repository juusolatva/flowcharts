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

bool ellipse(const QJsonArray &rect, QPainterPath &path) {
    if (rect.size() != 4)
        return false;
    for (const auto &v : rect) {
        if (!v.isDouble() || !std::isfinite(v.toDouble()))
            return false;
    }
    const qreal rx = rect[2].toDouble();
    const qreal ry = rect[3].toDouble();
    if (rx < 0 || ry < 0)
        return false;
    path.addEllipse(QRectF(rect[0].toDouble() - rx, -rect[1].toDouble() - ry, 2 * rx, 2 * ry));
    return true;
}

bool vertices(const QJsonArray &points, QVector<QPointF> &result) {
    if (points.isEmpty())
        return false;
    for (const auto &v : points) {
        QPointF p;
        if (!point(v, p))
            return false;
        result.append(p);
    }
    return true;
}

bool geometry(const QJsonObject &op, QPainterPath &path) {
    const auto kind = op["op"].toString();
    if (kind == "e" || kind == "E")
        return ellipse(op["rect"].toArray(), path);
    QVector<QPointF> points;
    if (!vertices(op["points"].toArray(), points))
        return false;
    path.moveTo(points[0]);
    if (kind == "b" || kind == "B") {
        if ((points.size() - 1) % 3 != 0)
            return false;
        for (qsizetype i = 1; i + 2 < points.size(); i += 3)
            path.cubicTo(points[i], points[i + 1], points[i + 2]);
        return true;
    }
    for (qsizetype i = 1; i < points.size(); ++i)
        path.lineTo(points[i]);
    if (kind == "p" || kind == "P")
        path.closeSubpath();
    return true;
}

// The pen, fill and font that later drawing operations inherit.
struct Style {
    QPen pen{Qt::black};
    QColor fill{Qt::black};
    QFont font{"Helvetica"};
    Style() { font.setPixelSize(14); }
};

bool setColor(const QJsonObject &op, bool stroke, Style &style, QString &error) {
    const auto c = color(op["color"].toString());
    if (!c.isValid()) {
        error = "Unsupported Graphviz color or gradient";
        return false;
    }
    if (stroke)
        style.pen.setColor(c);
    else
        style.fill = c;
    return true;
}

bool setFont(const QJsonObject &op, Style &style, QString &error) {
    const auto size = op["size"].toDouble();
    if (!std::isfinite(size) || size < 1 || size > 10000) {
        error = "Invalid Graphviz font size";
        return false;
    }
    style.font.setFamily(op["face"].toString());
    style.font.setPixelSize(qRound(size));
    return true;
}

void setFontFlags(const QJsonObject &op, Style &style) {
    const int flags = op["fontchar"].toInt();
    style.font.setBold((flags & 1) != 0);
    style.font.setItalic((flags & 2) != 0);
    style.font.setUnderline((flags & 4) != 0);
    style.font.setStrikeOut((flags & 32) != 0);
}

bool setLineWidth(const QString &name, QPen &pen, QString &error) {
    bool ok = false;
    const auto width = name.mid(13, name.size() - 14).toDouble(&ok);
    if (!ok || !std::isfinite(width) || width < 0 || width > 10000) {
        error = "Invalid Graphviz line width";
        return false;
    }
    pen.setWidthF(width);
    return true;
}

bool setLineStyle(const QJsonObject &op, QPen &pen, QString &error) {
    const auto name = op["style"].toString();
    if (name == "dashed")
        pen.setStyle(Qt::DashLine);
    else if (name == "dotted")
        pen.setStyle(Qt::DotLine);
    else if (name == "solid")
        pen.setStyle(Qt::SolidLine);
    else if (name == "bold")
        pen.setWidthF(2);
    else if (name.startsWith("setlinewidth(") && name.endsWith(')'))
        return setLineWidth(name, pen, error);
    else {
        error = "Unsupported Graphviz line style: " + name;
        return false;
    }
    return true;
}

bool addText(const QJsonObject &op, const Style &style, Drawing &drawing, QString &error) {
    Primitive primitive;
    primitive.isText = true;
    primitive.text = op["text"].toString();
    primitive.font = style.font;
    primitive.pen = style.pen;
    primitive.textWidth = op["width"].toDouble();
    if (!point(op["pt"], primitive.position) || !std::isfinite(primitive.textWidth) ||
        primitive.textWidth < 0) {
        error = "Invalid Graphviz text geometry";
        return false;
    }
    if (const auto align = op["align"].toString(); align == "c")
        primitive.position.rx() -= primitive.textWidth / 2;
    else if (align == "r")
        primitive.position.rx() -= primitive.textWidth;
    const QFontMetricsF metrics(style.font);
    drawing.bounds |= QRectF(primitive.position.x(), primitive.position.y() - metrics.ascent(),
                             primitive.textWidth, metrics.height());
    drawing.primitives.append(primitive);
    return true;
}

bool isShape(const QString &kind) {
    return kind == "e" || kind == "E" || kind == "p" || kind == "P" || kind == "b" || kind == "B" ||
           kind == "L";
}

bool addShape(const QJsonObject &op, const QString &kind, const Style &style, bool selectable,
              Drawing &drawing, QString &error) {
    Primitive primitive;
    primitive.pen = style.pen;
    if (kind == "E" || kind == "P" || kind == "B")
        primitive.brush = style.fill;
    if (!geometry(op, primitive.path)) {
        error = "Invalid Graphviz path geometry";
        return false;
    }
    drawing.bounds |= primitive.path.boundingRect().adjusted(-3, -3, 3, 3);
    if (selectable)
        drawing.hitShape.addPath(primitive.path);
    drawing.primitives.append(primitive);
    return true;
}

bool operation(const QJsonObject &op, Style &style, bool selectable, Drawing &drawing,
               QString &error) {
    const auto kind = op["op"].toString();
    if (kind == "c" || kind == "C")
        return setColor(op, kind == "c", style, error);
    if (kind == "F")
        return setFont(op, style, error);
    if (kind == "t") {
        setFontFlags(op, style);
        return true;
    }
    if (kind == "S")
        return setLineStyle(op, style.pen, error);
    if (kind == "T")
        return addText(op, style, drawing, error);
    if (isShape(kind))
        return addShape(op, kind, style, selectable, drawing, error);
    error = "Unsupported Graphviz drawing operation: " + kind;
    return false;
}

bool operations(const QJsonArray &ops, Drawing &drawing, bool selectable, QString &error) {
    Style style;
    for (const auto &value : ops) {
        if (!operation(value.toObject(), style, selectable, drawing, error))
            return false;
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
