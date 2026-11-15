// A protocol peer used only by QProcess integration tests.
//   --diagnostics-once   the first "open" snapshot carries one diagnostic message
//   --refresh-delay=MS   wait before answering "refresh"
//   --refresh-fails      answer "refresh" with an error
//   --open-fails         answer "open" with an error
//   --graph-delay=MS     wait before answering "graph"
#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStringList>
#include <QThread>

#include <iostream>
#include <string>

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    const auto arguments = app.arguments();
    const bool diagnosticsOnce = arguments.contains("--diagnostics-once");
    const bool refreshFails = arguments.contains("--refresh-fails");
    const bool openFails = arguments.contains("--open-fails");
    int refreshDelay = 0;
    int graphDelay = 0;
    for (const auto &argument : arguments) {
        if (argument.startsWith("--refresh-delay="))
            refreshDelay = argument.section('=', 1).toInt();
        if (argument.startsWith("--graph-delay="))
            graphDelay = argument.section('=', 1).toInt();
    }
    int generation = 0;
    std::string line;
    while (std::getline(std::cin, line)) {
        const auto request = QJsonDocument::fromJson(QByteArray::fromStdString(line)).object();
        const auto method = request["method"].toString();
        if (method == "refresh" && refreshDelay > 0)
            QThread::msleep(refreshDelay);
        if (method == "graph" && graphDelay > 0)
            QThread::msleep(graphDelay);
        const bool reject = method == "reject"; // as the worker answers an unreadable frame
        const bool fail = method == "fail" || reject || (method == "refresh" && refreshFails) ||
                          (method == "open" && openFails);
        QJsonObject response{{"protocol_version", method == "bad-version" ? 99 : 1},
                             {"id", reject ? QJsonValue::Null : request["id"]},
                             {"ok", !fail}};
        if (fail) {
            response["error"] = QJsonObject{{"code", "example"},
                                            {"message", method == "refresh" ? "refresh failed"
                                                        : method == "open"  ? "open failed"
                                                                            : "recoverable"}};
        } else if (method == "open") {
            ++generation;
            const auto messages =
                diagnosticsOnce && generation == 1 ? QJsonArray{"problem"} : QJsonArray{};
            response["result"] =
                QJsonObject{{"snapshot", QJsonObject{{"generation", generation},
                                                     {"entries", QJsonArray{}},
                                                     {"messages", messages},
                                                     {"documents", QJsonArray{}}}}};
        } else if (method == "refresh") {
            response["result"] = QJsonObject{{"changed", false}};
        } else {
            response["result"] = QJsonObject{};
        }
        const auto bytes = QJsonDocument(response).toJson(QJsonDocument::Compact);
        std::cout << bytes.toStdString() << '\n' << std::flush;
    }
    return 0;
}
