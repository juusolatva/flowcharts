#include "protocol.h"

#include <QJsonDocument>
#include <QJsonParseError>

namespace flowcharts {

QByteArray encodeRequest(qint64 id, const QString &method, const QJsonObject &params) {
    return QJsonDocument(QJsonObject{{"protocol_version", ProtocolVersion},
                                     {"id", id},
                                     {"method", method},
                                     {"params", params}})
               .toJson(QJsonDocument::Compact) +
           '\n';
}

bool FrameReader::feed(const QByteArray &bytes, QVector<QJsonObject> &frames, QString &error) {
    // Consume a chunk a frame at a time so a large batch of small frames is not rejected.
    qsizetype offset = 0;
    while (offset < bytes.size()) {
        const auto newline = bytes.indexOf('\n', offset);
        const auto end = newline < 0 ? bytes.size() : newline;
        if (m_buffer.size() + end - offset > m_limit) {
            error = "Engine response exceeds the frame size limit";
            return false;
        }
        m_buffer.append(bytes.constData() + offset, end - offset);
        if (newline < 0)
            return true;
        QJsonParseError parseError;
        const auto document = QJsonDocument::fromJson(m_buffer, &parseError);
        m_buffer.clear();
        if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
            error = "Invalid JSON response from engine: " + parseError.errorString();
            return false;
        }
        frames.append(document.object());
        offset = end + 1;
    }
    return true;
}

} // namespace flowcharts
