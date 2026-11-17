#include "drawing.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QtTest>

using namespace flowcharts;

namespace {

// Test JSON is written with single quotes to keep the literals readable.
QJsonObject draw(QByteArray ops) {
    ops.replace('\'', '"');
    return QJsonDocument::fromJson("{\"_draw_\":" + ops + "}").object();
}

} // namespace

class DrawingTest : public QObject {
    Q_OBJECT
private slots:
    void lineStylesApplyToLaterShapes() {
        Drawing drawing;
        QString error;
        const QByteArray ops = "[{'op':'S','style':'dotted'},"
                               "{'op':'L','points':[[0,0],[10,0]]},"
                               "{'op':'S','style':'solid'},"
                               "{'op':'S','style':'bold'},"
                               "{'op':'L','points':[[0,0],[10,0]]},"
                               "{'op':'S','style':'setlinewidth(3)'},"
                               "{'op':'L','points':[[0,0],[10,0]]}]";
        QVERIFY2(parseDrawing(draw(ops), drawing, error), qPrintable(error));
        QCOMPARE(drawing.primitives.size(), 3);
        QCOMPARE(drawing.primitives[0].pen.style(), Qt::DotLine);
        QCOMPARE(drawing.primitives[1].pen.style(), Qt::SolidLine);
        QCOMPARE(drawing.primitives[1].pen.widthF(), 2.0);
        QCOMPARE(drawing.primitives[2].pen.widthF(), 3.0);
    }
    void fontAndAlignmentApplyToText() {
        Drawing drawing;
        QString error;
        const QByteArray ops = "[{'op':'F','size':20,'face':'Courier'},"
                               "{'op':'t','fontchar':39},"
                               "{'op':'T','pt':[10,10],'align':'r','width':8,'text':'x'}]";
        QVERIFY2(parseDrawing(draw(ops), drawing, error), qPrintable(error));
        QCOMPARE(drawing.primitives.size(), 1);
        const auto &text = drawing.primitives[0];
        QVERIFY(text.isText);
        QCOMPARE(text.text, QString("x"));
        QCOMPARE(text.font.pixelSize(), 20);
        QVERIFY(text.font.bold());
        QVERIFY(text.font.italic());
        QVERIFY(text.font.underline());
        QVERIFY(text.font.strikeOut());
        QCOMPARE(text.position, QPointF(2, -10));
    }
    void fillColorAppliesToFilledShapesOnly() {
        Drawing drawing;
        QString error;
        const QByteArray ops = "[{'op':'C','color':'#ff000080'},"
                               "{'op':'P','points':[[0,0],[10,0],[10,10]]},"
                               "{'op':'p','points':[[0,0],[10,0],[10,10]]},"
                               "{'op':'E','rect':[5,5,2,3]}]";
        QVERIFY2(parseDrawing(draw(ops), drawing, error), qPrintable(error));
        QCOMPARE(drawing.primitives.size(), 3);
        QCOMPARE(drawing.primitives[0].brush.color(), QColor(255, 0, 0, 128));
        QCOMPARE(drawing.primitives[1].brush.style(), Qt::NoBrush);
        QCOMPARE(drawing.primitives[2].brush.color(), QColor(255, 0, 0, 128));
        QVERIFY(drawing.hitShape.contains(QPointF(5, -5)));
    }
    void invalidOperationsAreRejected_data() {
        QTest::addColumn<QByteArray>("ops");
        QTest::addColumn<QString>("message");
        QTest::newRow("unknown color") << QByteArray("[{'op':'c','color':'#zzzzzzzz'}]") << "color";
        QTest::newRow("font size") << QByteArray("[{'op':'F','size':0,'face':'x'}]") << "font size";
        QTest::newRow("line style") << QByteArray("[{'op':'S','style':'wavy'}]") << "line style";
        QTest::newRow("line width text")
            << QByteArray("[{'op':'S','style':'setlinewidth(abc)'}]") << "line width";
        QTest::newRow("negative line width")
            << QByteArray("[{'op':'S','style':'setlinewidth(-1)'}]") << "line width";
        QTest::newRow("text point")
            << QByteArray("[{'op':'T','pt':[1],'width':1}]") << "text geometry";
        QTest::newRow("text width")
            << QByteArray("[{'op':'T','pt':[1,1],'width':-1}]") << "text geometry";
        QTest::newRow("no points") << QByteArray("[{'op':'L','points':[]}]") << "path geometry";
        QTest::newRow("point type")
            << QByteArray("[{'op':'L','points':[['a',1]]}]") << "path geometry";
        QTest::newRow("bezier count")
            << QByteArray("[{'op':'b','points':[[0,0],[1,1],[2,2]]}]") << "path geometry";
        QTest::newRow("ellipse size")
            << QByteArray("[{'op':'e','rect':[1,1,1]}]") << "path geometry";
        QTest::newRow("ellipse type")
            << QByteArray("[{'op':'e','rect':[1,1,1,'a']}]") << "path geometry";
        QTest::newRow("ellipse radius")
            << QByteArray("[{'op':'E','rect':[1,1,-1,1]}]") << "path geometry";
        QTest::newRow("operation") << QByteArray("[{'op':'Z'}]") << "drawing operation";
    }
    void invalidOperationsAreRejected() {
        QFETCH(QByteArray, ops);
        QFETCH(QString, message);
        Drawing drawing;
        QString error;
        QVERIFY(!parseDrawing(draw(ops), drawing, error));
        QVERIFY2(error.contains(message), qPrintable(error));
    }
};
QTEST_MAIN(DrawingTest)
#include "test_drawing.moc"
