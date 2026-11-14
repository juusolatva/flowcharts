#pragma once

#include "protocol.h"

#include <QObject>
#include <QProcess>
#include <QTimer>
#include <optional>

namespace flowcharts {

// The UI knows a protocol, not Python. A future C++ engine can implement the same contract.
class EngineClient : public QObject {
    Q_OBJECT
public:
    explicit EngineClient(QObject *parent = nullptr);
    ~EngineClient() override;
    void start(const QString &program, const QStringList &arguments);
    qint64 request(const QString &method, const QJsonObject &params);
    bool idle() const;
    bool running() const;

signals:
    void succeeded(qint64 id, const QString &method, const QJsonObject &result);
    void failed(qint64 id, const QString &method, const QString &code, const QString &message);
    void fatalError(const QString &message);
    void busyChanged(bool busy);

private:
    struct Request {
        qint64 id;
        QString method;
        QJsonObject params;
    };
    void dispatch();
    void readOutput();
    void accept(const QJsonObject &response);
    void fail(const QString &message);
    void stop();

    QProcess m_process;
    QTimer m_deadline;
    FrameReader m_reader;
    QVector<Request> m_queue;
    std::optional<Request> m_active;
    QByteArray m_stderr;
    qint64 m_nextId = 1;
    bool m_failed = false;
    bool m_stopping = false;
};

} // namespace flowcharts
