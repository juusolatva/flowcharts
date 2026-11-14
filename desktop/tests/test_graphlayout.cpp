#include "graphlayout.h"

#include <QFile>
#include <QJsonArray>
#include <QtTest>

using namespace flowcharts;

class GraphLayoutTest : public QObject {
    Q_OBJECT
private slots:
    void ellipseTextBezierAndCluster() {
        QFile fixture(QFINDTESTDATA("fixtures/graphviz.json"));
        QVERIFY(fixture.open(QIODevice::ReadOnly));
        auto json = QJsonDocument::fromJson(fixture.readAll()).object();
        GraphLayout graph;
        QString error;
        QVERIFY2(parseLayout(json, graph, error), qPrintable(error));
        QCOMPARE(graph.nodes.size(), 1);
        QCOMPARE(graph.decorations.size(), 1);
        QCOMPARE(graph.edges.size(), 1);
        QCOMPARE(graph.nodes[0].id, QString("f#start"));
        QVERIFY(graph.nodes[0].drawing.hitShape.contains(QPointF(50, -150)));
        QVERIFY(!graph.nodes[0].drawing.hitShape.contains(QPointF(10, 10)));
        const auto &outline = graph.nodes[0].drawing.primitives[0];
        QCOMPARE(outline.pen.color(), QColor(0x11, 0x22, 0x33, 0x44));
        QCOMPARE(graph.edges[0].primitives[0].pen.style(), Qt::DashLine);
        QVERIFY(graph.edges[0].primitives[0].path.elementCount() >= 4);
        QCOMPARE(graph.nodes[0].drawing.primitives[1].position, QPointF(40, -146));
    }
    void invalidBoundsAndUnsupportedDrawingFailExplicitly() {
        GraphLayout graph;
        QString error;
        QVERIFY(!parseLayout({}, graph, error));
        QVERIFY(!error.isEmpty());
        QVERIFY(!parseLayout(QJsonDocument::fromJson(R"({"bb":"0,0,10,10","objects":[
          {"name":"a","_draw_":[{"op":"unsupported"}]}]})")
                                 .object(),
                             graph, error));
        QVERIFY(error.contains("unsupported"));
    }
    void emptyCallgraphIsValid() {
        GraphLayout graph;
        QString error;
        QVERIFY(parseLayout({{"bb", "0,0,0,0"}}, graph, error));
        QVERIFY(graph.nodes.isEmpty());
    }
};
QTEST_MAIN(GraphLayoutTest)
#include "test_graphlayout.moc"
