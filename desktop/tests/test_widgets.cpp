#include "graphview.h"
#include "sourceview.h"

#include <QScrollBar>
#include <QSignalSpy>
#include <QtTest>

using namespace flowcharts;

static GraphLayout graph() {
    GraphLayout result;
    result.bounds = QRectF(0, 0, 1000, 1000);
    Drawing drawing;
    drawing.hitShape.addRect(40, 40, 60, 40);
    drawing.bounds = drawing.hitShape.boundingRect().adjusted(-3, -3, 3, 3);
    result.nodes.append({"node", drawing});
    return result;
}

class WidgetsTest : public QObject {
    Q_OBJECT
private slots:
    void retainsZoomAndSelectionOnlyForSameChart() {
        GraphView view;
        view.resize(600, 400);
        view.show();
        view.setGraph(graph(), "a.py/f");
        view.zoom(1.4);
        view.selectNode("node");
        auto transform = view.transform();
        auto center = view.mapToScene(view.viewport()->rect().center());
        view.setGraph(graph(), "a.py/f");
        QCOMPARE(view.transform(), transform);
        QCOMPARE(view.selectedNode(), QString("node"));
        QVERIFY(QLineF(center, view.mapToScene(view.viewport()->rect().center())).length() < 4);
        view.setGraph(graph(), "a.py/g");
        QVERIFY(view.selectedNode().isEmpty());
        QVERIFY(view.transform() != transform);
    }
    void sourceHighlightIsReadOnlyAndBounded() {
        SourceView source;
        source.setPlainText("one\ntwo\nthree\n");
        QVERIFY(source.isReadOnly());
        source.highlightLines(2, 3);
        QCOMPARE(source.extraSelections().size(), 2);
        source.highlightLines(100, 200);
        QVERIFY(source.extraSelections().isEmpty());
        source.highlightLines(1, 1);
        QCOMPARE(source.extraSelections().size(), 1);
    }
    void nodeSelectionEmitsIdentity() {
        GraphView view;
        view.setGraph(graph(), "chart");
        QSignalSpy spy(&view, &GraphView::nodeSelected);
        view.selectNode("node");
        QCOMPARE(spy.size(), 1);
        QCOMPARE(spy[0][0].toString(), QString("node"));
    }
};
QTEST_MAIN(WidgetsTest)
#include "test_widgets.moc"
