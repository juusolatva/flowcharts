// A protocol peer used only by QProcess integration tests.
#include <QCoreApplication>
#include <QJsonDocument>
#include <QJsonObject>

#include <iostream>
#include <string>

int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    std::string line;
    while (std::getline(std::cin, line)) {
        const auto request = QJsonDocument::fromJson(QByteArray::fromStdString(line)).object();
        const auto method = request["method"].toString();
        const bool reject = method == "reject"; // as the worker answers an unreadable frame
        const bool fail = method == "fail" || reject;
        QJsonObject response{{"protocol_version", method == "bad-version" ? 99 : 1},
                             {"id", reject ? QJsonValue::Null : request["id"]},
                             {"ok", !fail}};
        if (fail)
            response["error"] = QJsonObject{{"code", "example"}, {"message", "recoverable"}};
        else
            response["result"] = QJsonObject{};
        const auto bytes = QJsonDocument(response).toJson(QJsonDocument::Compact);
        std::cout << bytes.toStdString() << '\n' << std::flush;
    }
    return 0;
}
