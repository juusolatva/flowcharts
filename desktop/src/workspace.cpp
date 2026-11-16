#include "workspace.h"

#include <limits>

namespace flowcharts {

bool Workspace::setSnapshot(const QJsonObject &snapshot, QString &error) {
    if (!snapshot["generation"].isDouble() || snapshot["generation"].toInt() < 1 ||
        !snapshot["entries"].isArray() || !snapshot["documents"].isArray()) {
        error = "Malformed workspace snapshot from engine";
        return false;
    }
    for (const auto &value : snapshot["documents"].toArray()) {
        const auto entry = value.toObject();
        const auto doc = entry["document"].toObject();
        if (doc["schema_version"] != QJsonValue(3)) {
            error = "Unsupported document schema; this GUI requires IR schema version 3";
            return false;
        }
        if (!entry["source_text"].isString() || !doc["source"].isString() ||
            !doc["functions"].isArray()) {
            error = "Malformed document in workspace snapshot";
            return false;
        }
    }
    m_snapshot = snapshot;
    return true;
}

QJsonObject Workspace::document(int index) const {
    const auto docs = m_snapshot["documents"].toArray();
    return index < 0 || index >= docs.size() ? QJsonObject{} : docs[index].toObject();
}

QString Workspace::sourceText(int index) const {
    return document(index)["source_text"].toString();
}
QString Workspace::sourcePath(int index) const {
    return document(index)["document"].toObject()["source"].toString();
}

namespace {

// Fills in why the named function was skipped, when the file's skipped list names it.
void setSkipped(const QJsonArray &skipped, const QString &qualname, FileView &view) {
    for (const auto &value : skipped) {
        const auto entry = value.toObject();
        if (entry["qualname"].toString() == qualname) {
            view.message = entry["message"].toString();
            view.line = entry["line"].toInt();
            return;
        }
    }
}

} // namespace

std::optional<FileView> Workspace::fileView(const FileRef &ref) const {
    for (const auto &value : entries()) {
        const auto entry = value.toObject();
        if (entry["source"].toString() != ref.source)
            continue;
        FileView result;
        if (entry["doc"].isDouble())
            result.document = entry["doc"].toInt();
        result.message = entry["error"].toString();
        if (result.message.isEmpty() && !ref.qualname.isEmpty())
            setSkipped(entry["skipped"].toArray(), ref.qualname, result);
        return result;
    }
    return std::nullopt;
}

QString Workspace::key(const ChartRef &ref) const {
    return ref.document < 0 ? "<callgraph>" : sourcePath(ref.document) + '\n' + ref.qualname;
}

QJsonObject Workspace::chart(const ChartRef &ref) const {
    const auto doc = document(ref.document)["document"].toObject();
    if (ref.qualname == "<module>")
        return doc["module"].toObject();
    for (const auto &value : doc["functions"].toArray()) {
        if (value.toObject()["qualname"].toString() == ref.qualname)
            return value.toObject();
    }
    return {};
}

QJsonObject Workspace::node(const ChartRef &ref, const QString &id) const {
    for (const auto &value : chart(ref)["nodes"].toArray()) {
        if (value.toObject()["id"].toString() == id)
            return value.toObject();
    }
    return {};
}

QString Workspace::nodeTitle(const ChartRef &ref, const QString &id) const {
    if (ref.document >= 0)
        return node(ref, id)["label"].toString().section('\n', 0, 0);
    const auto function = target(ref, id);
    if (!function)
        return {};
    const QJsonObject doc = document(function->document)["document"].toObject();
    const QString module = doc.value("module_name").toString();
    if (function->qualname == "<module>")
        return module + " (module)";
    return module + '.' + function->qualname;
}

QString Workspace::nodeForLine(const ChartRef &ref, int line) const {
    QString best;
    int bestSpan = std::numeric_limits<int>::max();
    for (const auto &value : chart(ref)["nodes"].toArray()) {
        const auto n = value.toObject();
        if (!n["location"].isObject())
            continue;
        const auto loc = n["location"].toObject();
        const int first = loc["line"].toInt();
        const int last = loc["end_line"].toInt();
        if (first <= line && line <= last && last - first < bestSpan) {
            best = n["id"].toString();
            bestSpan = last - first;
        }
    }
    return best;
}

std::optional<ChartRef> Workspace::findChart(const QString &source, const QString &qualname) const {
    const auto docs = m_snapshot["documents"].toArray();
    for (int i = 0; i < docs.size(); ++i) {
        ChartRef ref{i, qualname};
        if (sourcePath(i) == source && !chart(ref).isEmpty())
            return ref;
    }
    return std::nullopt;
}

std::optional<ChartRef> Workspace::target(const ChartRef &ref, const QString &id) const {
    if (ref.document < 0) {
        const int separator = id.indexOf('#');
        bool ok = false;
        const int index = id.left(separator).toInt(&ok);
        if (ChartRef result{index, id.mid(separator + 1)};
            separator > 0 && ok && index >= 0 && !chart(result).isEmpty())
            return result;
        return std::nullopt;
    }
    std::optional<ChartRef> result;
    for (const auto &value : chart(ref)["calls"].toArray()) {
        const auto call = value.toObject();
        if (call["node"].toString() != id || !call["target"].isObject())
            continue;
        const auto target = call["target"].toObject();
        const auto docs = m_snapshot["documents"].toArray();
        for (int i = 0; i < docs.size(); ++i) {
            const auto doc = document(i)["document"].toObject();
            ChartRef candidate{i, target["qualname"].toString()};
            if (doc["module_name"] != target["module"] || chart(candidate).isEmpty())
                continue;
            if (result && !(*result == candidate))
                return std::nullopt;
            result = candidate;
        }
    }
    return result;
}

QStringList Workspace::diagnostics() const {
    QStringList messages;
    for (const auto &message : m_snapshot["messages"].toArray())
        messages.append(message.toString());
    for (const auto &value : entries()) {
        const auto entry = value.toObject();
        if (entry["error"].isString() && !messages.contains(entry["error"].toString()))
            messages.append(entry["error"].toString());
        for (const auto &skipped : entry["skipped"].toArray()) {
            const auto warning = skipped.toObject();
            messages.append(QString("%1:%2: %3: %4")
                                .arg(entry["source"].toString())
                                .arg(warning["line"].toInt())
                                .arg(warning["qualname"].toString())
                                .arg(warning["message"].toString()));
        }
    }
    return messages;
}

} // namespace flowcharts
