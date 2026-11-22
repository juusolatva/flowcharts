#include "chartbrowser.h"
#include "graphview.h"
#include "sourceview.h"

#include <QLineEdit>
#include <QScrollBar>
#include <QSignalSpy>
#include <QTreeView>
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
    void filteringDoesNotNavigateOrPreventExplicitSelection() {
        const QJsonArray functions{QJsonObject{{"qualname", "f"}}, QJsonObject{{"qualname", "g"}}};
        Workspace workspace;
        QString error;
        QVERIFY(workspace.setSnapshot(
            {{"generation", 1},
             {"entries",
              QJsonArray{QJsonObject{
                  {"source", "/a.py"}, {"key", "a"}, {"doc", 0}, {"functions", functions}}}},
             {"documents",
              QJsonArray{QJsonObject{{"source_text", ""},
                                     {"document", QJsonObject{{"schema_version", 3},
                                                              {"source", "/a.py"},
                                                              {"functions", functions}}}}}}},
            error));
        ChartBrowser browser;
        browser.setWorkspace(workspace);
        auto *search = browser.findChild<QLineEdit *>();
        auto *tree = browser.findChild<QTreeView *>();
        QSignalSpy charts(&browser, &ChartBrowser::chartSelected);
        QSignalSpy files(&browser, &ChartBrowser::fileSelected);
        browser.selectChart({});
        search->setText("f");
        QVERIFY(charts.isEmpty());
        QVERIFY(files.isEmpty());
        browser.selectChart({0, "f"});
        search->setText("g");
        QVERIFY(charts.isEmpty());
        QVERIFY(files.isEmpty());
        QVERIFY(!tree->currentIndex().isValid());
        const auto file = tree->model()->index(1, 0);
        const auto function = tree->model()->index(0, 0, file);
        QCOMPARE(function.data().toString(), QString("g"));
        tree->setCurrentIndex(function);
        QCOMPARE(charts.size(), 1);
        QCOMPARE(charts[0][1].toString(), QString("g"));
        search->clear();
        QCOMPARE(charts.size(), 1);
        QVERIFY(files.isEmpty());
        QCOMPARE(tree->currentIndex().data().toString(), QString("g"));
    }
    void extensionlessFilesHaveNoTrailingDot() {
        Workspace workspace;
        QString error;
        QVERIFY(workspace.setSnapshot(
            {{"generation", 1},
             {"entries",
              QJsonArray{
                  QJsonObject{{"source", "/Makefile"}, {"key", "Makefile"}, {"doc", 0}},
                  QJsonObject{{"source", "/a.py"}, {"key", "a"}, {"doc", 1}},
              }},
             {"documents",
              QJsonArray{QJsonObject{{"source_text", ""},
                                     {"document", QJsonObject{{"schema_version", 3},
                                                              {"source", "/Makefile"},
                                                              {"functions", QJsonArray{}}}}},
                         QJsonObject{{"source_text", ""},
                                     {"document", QJsonObject{{"schema_version", 3},
                                                              {"source", "/a.py"},
                                                              {"functions", QJsonArray{}}}}}}}},
            error));
        ChartBrowser browser;
        browser.setWorkspace(workspace);
        auto *model = browser.findChild<QTreeView *>()->model();
        QCOMPARE(model->index(1, 0).data().toString(), QString("Makefile"));
        QCOMPARE(model->index(2, 0).data().toString(), QString("a.py"));
    }
    void programmaticSelectionScrollsTreeWithoutNavigating() {
        QJsonArray functions;
        for (int i = 0; i < 200; ++i)
            functions.append(QJsonObject{{"qualname", QString("f%1").arg(i)}});
        Workspace workspace;
        QString error;
        QVERIFY(workspace.setSnapshot(
            {{"generation", 1},
             {"entries",
              QJsonArray{QJsonObject{
                  {"source", "/a.py"}, {"key", "a"}, {"doc", 0}, {"functions", functions}}}},
             {"documents",
              QJsonArray{QJsonObject{{"source_text", ""},
                                     {"document", QJsonObject{{"schema_version", 3},
                                                              {"source", "/a.py"},
                                                              {"functions", functions}}}}}}},
            error));
        ChartBrowser browser;
        browser.resize(250, 200);
        browser.setWorkspace(workspace);
        browser.show();
        const auto *tree = browser.findChild<QTreeView *>();
        QSignalSpy charts(&browser, &ChartBrowser::chartSelected);
        QSignalSpy files(&browser, &ChartBrowser::fileSelected);
        QSignalSpy current(tree->selectionModel(), &QItemSelectionModel::currentChanged);
        browser.selectChart({0, "f199"});
        QCOMPARE(tree->currentIndex().data().toString(), QString("f199"));
        QVERIFY(current.size() >= 1);
        QVERIFY(tree->viewport()->rect().intersects(tree->visualRect(tree->currentIndex())));
        browser.selectFile({"/a.py", {}});
        QCOMPARE(tree->currentIndex().data().toString(), QString("a.py"));
        QVERIFY(tree->viewport()->rect().intersects(tree->visualRect(tree->currentIndex())));
        QVERIFY(charts.isEmpty());
        QVERIFY(files.isEmpty());
    }
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
