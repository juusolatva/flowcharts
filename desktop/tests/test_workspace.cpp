#include "workspace.h"

#include <QJsonArray>
#include <QtTest>

using namespace flowcharts;

static QJsonObject fixture() {
    const auto location = [](int first, int last) {
        return QJsonObject{{"line", first}, {"end_line", last}};
    };
    QJsonObject chart{
        {"qualname", "f"},
        {"nodes", QJsonArray{QJsonObject{{"id", "start"}, {"location", QJsonValue::Null}},
                             QJsonObject{{"id", "outer"}, {"location", location(1, 10)}},
                             QJsonObject{{"id", "inner"}, {"location", location(3, 4)}},
                             QJsonObject{{"id", "copy"}, {"location", location(3, 4)}}}},
        {"calls",
         QJsonArray{QJsonObject{{"node", "inner"},
                                {"text", "g"},
                                {"target", QJsonObject{{"module", "a"}, {"qualname", "g"}}}}}}};
    QJsonObject doc{{"schema_version", 3},
                    {"source", "/a.py"},
                    {"module_name", "a"},
                    {"functions", QJsonArray{chart, QJsonObject{{"qualname", "g"}}}}};
    return {{"generation", 1},
            {"entries", QJsonArray{}},
            {"documents", QJsonArray{QJsonObject{{"document", doc}, {"source_text", "hello"}}}}};
}

class WorkspaceTest : public QObject {
    Q_OBJECT
private slots:
    void sourceAndStableIdentity() {
        Workspace model;
        QString error;
        QVERIFY(model.setSnapshot(fixture(), error));
        QCOMPARE(model.generation(), 1);
        QCOMPARE(model.sourceText(0), QString("hello"));
        QCOMPARE(model.key({0, "f"}), QString("/a.py\nf"));
        QVERIFY(model.findChart("/a.py", "f") == ChartRef(0, "f"));
        QVERIFY(model.chart({-1, {}}).isEmpty());
    }
    void choosesSmallestSpanAndKeepsFirstFinallyCopy() {
        Workspace model;
        QString error;
        QVERIFY(model.setSnapshot(fixture(), error));
        QCOMPARE(model.nodeForLine({0, "f"}, 3), QString("inner"));
        QCOMPARE(model.nodeForLine({0, "f"}, 8), QString("outer"));
        QVERIFY(model.nodeForLine({0, "f"}, 99).isEmpty());
        QCOMPARE(model.node({0, "f"}, "inner")["location"].toObject()["line"].toInt(), 3);
    }
    void resolvesCallAndCallgraphNavigation() {
        Workspace model;
        QString error;
        QVERIFY(model.setSnapshot(fixture(), error));
        QVERIFY(model.target({0, "f"}, "inner") == ChartRef(0, "g"));
        QVERIFY(model.target({}, "0#f") == ChartRef(0, "f"));
        QVERIFY(!model.target({}, "-1#f").has_value());
        QVERIFY(!model.target({}, "oops#f").has_value());
        QVERIFY(!model.target({0, "f"}, "outer").has_value());
    }
    void rejectsUnknownSchemaAndMalformedSnapshotsAtomically() {
        Workspace model;
        QString error;
        QVERIFY(model.setSnapshot(fixture(), error));
        QVERIFY(!model.setSnapshot({}, error));
        QCOMPARE(model.generation(), 1);
        auto snapshot = fixture();
        auto documents = snapshot["documents"].toArray();
        auto entry = documents[0].toObject();
        auto doc = entry["document"].toObject();
        doc["schema_version"] = 99;
        entry["document"] = doc;
        documents[0] = entry;
        snapshot["documents"] = documents;
        QVERIFY(!model.setSnapshot(snapshot, error));
        QVERIFY(error.contains("schema"));
    }
};
QTEST_GUILESS_MAIN(WorkspaceTest)
#include "test_workspace.moc"
