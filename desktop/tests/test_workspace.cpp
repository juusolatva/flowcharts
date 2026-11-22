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
    void nodeTitlesNameCallGraphFunctions() {
        auto snapshot = fixture();
        auto documents = snapshot["documents"].toArray();
        auto entry = documents[0].toObject();
        auto doc = entry["document"].toObject();
        auto functions = doc["functions"].toArray();
        auto chart = functions[0].toObject();
        auto nodes = chart["nodes"].toArray();
        auto outer = nodes[1].toObject();
        outer["label"] = "if x:\nmore";
        nodes[1] = outer;
        chart["nodes"] = nodes;
        functions[0] = chart;
        doc["functions"] = functions;
        doc["module"] = QJsonObject{{"qualname", "<module>"}};
        entry["document"] = doc;
        documents[0] = entry;
        snapshot["documents"] = documents;
        Workspace model;
        QString error;
        QVERIFY(model.setSnapshot(snapshot, error));
        QCOMPARE(model.nodeTitle({0, "f"}, "outer"), QString("if x:"));
        QCOMPARE(model.nodeTitle({}, "0#g"), QString("a.g"));
        QCOMPARE(model.nodeTitle({}, "0#<module>"), QString("a (module)"));
        QVERIFY(model.nodeTitle({}, "7#g").isEmpty());
        QVERIFY(model.nodeTitle({0, "f"}, "missing").isEmpty());
    }
    void nodeTitlesFallBackToTheSourceWithoutAModuleName() {
        // A top-level __init__.py has no module name; its call-graph cluster shows the path.
        auto snapshot = fixture();
        auto documents = snapshot["documents"].toArray();
        auto entry = documents[0].toObject();
        auto doc = entry["document"].toObject();
        doc["module_name"] = "";
        doc["source"] = "/pkg/__init__.py";
        doc["module"] = QJsonObject{{"qualname", "<module>"}};
        entry["document"] = doc;
        documents[0] = entry;
        snapshot["documents"] = documents;
        Workspace model;
        QString error;
        QVERIFY(model.setSnapshot(snapshot, error));
        QCOMPARE(model.nodeTitle({}, "0#g"), QString("/pkg/__init__.py: g"));
        QCOMPARE(model.nodeTitle({}, "0#<module>"), QString("/pkg/__init__.py (module)"));
    }
    void diagnosticsKeepPercentSignsAndOmitMissingLines() {
        auto snapshot = fixture();
        snapshot["entries"] = QJsonArray{QJsonObject{
            {"source", "/odd%2%3.py"},
            {"doc", 0},
            {"skipped",
             QJsonArray{QJsonObject{{"qualname", "f"}, {"message", "syntax error"}, {"line", 4}},
                        QJsonObject{{"qualname", "<module>"},
                                    {"message", "too large"},
                                    {"line", QJsonValue::Null}}}}}};
        Workspace model;
        QString error;
        QVERIFY(model.setSnapshot(snapshot, error));
        QCOMPARE(model.diagnostics(), QStringList({"/odd%2%3.py:4: f: syntax error",
                                                   "/odd%2%3.py: <module>: too large"}));
    }
    void fileViewsUseStablePathsAndCurrentDiagnostics() {
        auto snapshot = fixture();
        snapshot["entries"] = QJsonArray{QJsonObject{
            {"source", "/a.py"},
            {"doc", 0},
            {"skipped", QJsonArray{QJsonObject{
                            {"qualname", "bad"}, {"message", "invalid break"}, {"line", 4}}}}}};
        Workspace model;
        QString error;
        QVERIFY(model.setSnapshot(snapshot, error));
        const auto file = model.fileView({"/a.py", {}});
        QVERIFY(file.has_value());
        QCOMPARE(file->document, 0);
        QVERIFY(file->message.isEmpty());
        const auto skipped = model.fileView({"/a.py", "bad"});
        QVERIFY(skipped.has_value());
        QCOMPARE(skipped->line, 4);
        QCOMPARE(skipped->message, QString("invalid break"));
        QVERIFY(!model.fileView({"/gone.py", {}}).has_value());
        snapshot["entries"] = QJsonArray{
            QJsonObject{{"source", "/a.py"}, {"doc", QJsonValue::Null}, {"error", "cannot read"}}};
        QVERIFY(model.setSnapshot(snapshot, error));
        const auto failed = model.fileView({"/a.py", "bad"});
        QVERIFY(failed.has_value());
        QCOMPARE(failed->document, -1);
        QCOMPARE(failed->message, QString("cannot read"));
        QCOMPARE(failed->line, 0);
        snapshot["entries"] = QJsonArray{QJsonObject{{"source", "/a.py"}, {"doc", 0}}};
        QVERIFY(model.setSnapshot(snapshot, error));
        const auto fixed = model.fileView({"/a.py", "bad"});
        QVERIFY(fixed.has_value());
        QVERIFY(fixed->message.isEmpty());
        QCOMPARE(fixed->line, 0);
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
        for (const auto &id : {"", "0", "#f", "0#", "0#missing", "999#f"})
            QVERIFY2(!model.target({}, id).has_value(), id);
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
