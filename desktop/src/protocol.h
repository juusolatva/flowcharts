#pragma once

#include <QByteArray>
#include <QJsonObject>
#include <QVector>

namespace flowcharts {

inline constexpr int ProtocolVersion = 1;

QByteArray encodeRequest(qint64 id, const QString &method, const QJsonObject &params);

class FrameReader {
public:
    // A snapshot carries every document and its source, so it grows with the workspace.
    explicit FrameReader(qsizetype limit = 512 * 1024 * 1024) : m_limit(limit) {}
    bool feed(const QByteArray &bytes, QVector<QJsonObject> &frames, QString &error);
    void clear() { m_buffer.clear(); }

private:
    QByteArray m_buffer;
    qsizetype m_limit;
};

} // namespace flowcharts
