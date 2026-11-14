#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <optional>

namespace flowcharts {

struct ChartRef {
    int document = -1; // -1 denotes the run's call graph
    QString qualname;
    ChartRef() = default;
    ChartRef(int doc, const QString &name) : document(doc), qualname(name) {}
    bool operator==(const ChartRef &other) const {
        return document == other.document && qualname == other.qualname;
    }
};

struct FileRef {
    QString source;
    QString qualname; // Empty for a file; otherwise the selected skipped function.
};

struct FileView {
    int document = -1;
    QString message;
    int line = 0;
};

// Semantic data only. Geometry, widget state and subprocess management live elsewhere.
class Workspace {
public:
    bool setSnapshot(const QJsonObject &snapshot, QString &error);
    int generation() const { return m_snapshot["generation"].toInt(); }
    QJsonArray entries() const { return m_snapshot["entries"].toArray(); }
    QStringList diagnostics() const;
    QString sourceText(int document) const;
    QString sourcePath(int document) const;
    std::optional<FileView> fileView(const FileRef &ref) const;
    QString key(const ChartRef &ref) const;
    QJsonObject chart(const ChartRef &ref) const;
    QJsonObject node(const ChartRef &ref, const QString &id) const;
    QString nodeForLine(const ChartRef &ref, int line) const;
    std::optional<ChartRef> findChart(const QString &source, const QString &qualname) const;
    std::optional<ChartRef> target(const ChartRef &ref, const QString &node) const;

private:
    QJsonObject document(int index) const;
    QJsonObject m_snapshot;
};

} // namespace flowcharts
