/**
 * @file   topic_hz_monitor.cpp
 * @brief  Lightweight, generic topic-rate monitor.
 *
 * Subscribes to an arbitrary list of topics with type-erased (generic)
 * subscriptions — it never deserializes the payload, it only counts arrivals —
 * and republishes each topic's measured frequency as std_msgs/Float64 on
 * "<topic>/hz".
 *
 * Why C++: measuring Hz in the Python web manager meant rclpy delivered every
 * message to Python (executor wakeup + GIL + object/bytes churn). For a 97 Hz
 * IMU and 6 MB point clouds that pinned a core. Here the per-message cost is a
 * native callback that does a single atomic increment, so monitoring the same
 * firehose is a few percent of a core. The web manager then subscribes only to
 * the tiny 1 Hz "/hz" topics.
 *
 * Self-contained: depends only on rclcpp + std_msgs, so it can be lifted into
 * its own package unchanged.
 */
#include <atomic>
#include <deque>
#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/float64.hpp"

class TopicHzMonitor : public rclcpp::Node
{
public:
  TopicHzMonitor()
  : rclcpp::Node("topic_hz_monitor")
  {
    topics_ = this->declare_parameter<std::vector<std::string>>(
      "topics", std::vector<std::string>{});
    const double rate = this->declare_parameter<double>("publish_rate", 1.0);
    publish_period_ = (rate > 0.0) ? 1.0 / rate : 1.0;
    // Rate is averaged over a trailing window, not just the last publish tick.
    // A 1 s window is fragile for a ~1 Hz topic (±1 count = ±1 Hz, 0 = N/A) and
    // especially for a large RELIABLE one (e.g. the 5.76 MB visible_sync), whose
    // multi-fragment reassembly is delivered in bursts when the single-threaded
    // executor is busy with the 30 Hz LWIR + 6 MB cloud: some 1 s windows then
    // see 0 (N/A) and others 3-4. Averaging over a few seconds rides that out.
    rate_window_s_ = this->declare_parameter<double>("rate_window", 5.0);

    // Reader QoS is chosen per topic in discover() to MIRROR the publisher's
    // reliability. A blanket BEST_EFFORT reader is QoS-compatible with any
    // publisher, but it silently loses large RELIABLE samples: a 5.76 MB visible
    // image fragments into many UDP datagrams and, best-effort, one lost fragment
    // drops the whole sample with no retransmit — so the rate reads ~0 (N/A) even
    // though the topic publishes fine (small topics like the 0.3 MB LWIR survive).
    // Mirroring reliability fixes the big reliable topics while staying compatible
    // with the best-effort sensor topics (/ouster/points, /ouster/imu). Depth is
    // generous so bursts are counted, not dropped, between publish ticks.
    qos_ = rclcpp::QoS(rclcpp::KeepLast(50)).best_effort();

    if (topics_.empty()) {
      RCLCPP_WARN(get_logger(),
        "No 'topics' parameter set — monitoring nothing.");
    }

    // Topics may not exist yet at startup; (re)try to attach until each is up.
    discovery_timer_ = this->create_wall_timer(
      std::chrono::seconds(2), std::bind(&TopicHzMonitor::discover, this));
    discover();

    publish_timer_ = this->create_wall_timer(
      std::chrono::duration<double>(publish_period_),
      std::bind(&TopicHzMonitor::publishRates, this));
  }

private:
  struct Mon
  {
    std::atomic<uint64_t> count{0};
    // (time, cumulative count) samples taken at each publish tick; trimmed to
    // the trailing rate window. Rate = count delta / time span across the window.
    std::deque<std::pair<rclcpp::Time, uint64_t>> samples;
    rclcpp::GenericSubscription::SharedPtr sub;
    rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr pub;
  };

  void discover()
  {
    const auto names_types = this->get_topic_names_and_types();
    for (const auto & topic : topics_) {
      auto & m = mons_[topic];
      if (!m) {
        m = std::make_shared<Mon>();
      }
      if (m->sub) {
        continue;                       // already attached
      }
      const auto it = names_types.find(topic);
      if (it == names_types.end() || it->second.empty()) {
        continue;                       // not advertised yet
      }
      const std::string type = it->second.front();
      Mon * mp = m.get();
      const rclcpp::QoS sub_qos = readerQosFor(topic);
      const bool reliable =
        sub_qos.get_rmw_qos_profile().reliability == RMW_QOS_POLICY_RELIABILITY_RELIABLE;
      try {
        m->sub = this->create_generic_subscription(
          topic, type, sub_qos,
          [mp](std::shared_ptr<const rclcpp::SerializedMessage>) {
            mp->count.fetch_add(1, std::memory_order_relaxed);
          });
        m->pub = this->create_publisher<std_msgs::msg::Float64>(topic + "/hz", 10);
        RCLCPP_INFO(get_logger(), "Monitoring %s [%s] (%s) -> %s/hz",
          topic.c_str(), type.c_str(),
          reliable ? "reliable" : "best_effort", topic.c_str());
      } catch (const std::exception & e) {
        RCLCPP_WARN(get_logger(),
          "Could not attach to %s [%s]: %s (will retry)",
          topic.c_str(), type.c_str(), e.what());
        m->sub.reset();
      }
    }
  }

  // Build the reader QoS for one topic by mirroring its publisher(s):
  // RELIABLE only if every current publisher is reliable (so we receive its
  // large fragmented samples intact), else BEST_EFFORT (the only profile
  // compatible with a best-effort writer). Called once per topic, when it is
  // first discovered as advertised — so at least one publisher exists.
  rclcpp::QoS readerQosFor(const std::string & topic)
  {
    rclcpp::QoS qos(rclcpp::KeepLast(50));
    const auto infos = this->get_publishers_info_by_topic(topic);
    bool all_reliable = !infos.empty();
    for (const auto & info : infos) {
      if (info.qos_profile().get_rmw_qos_profile().reliability
            != RMW_QOS_POLICY_RELIABILITY_RELIABLE) {
        all_reliable = false;
        break;
      }
    }
    return all_reliable ? qos.reliable() : qos.best_effort();
  }

  void publishRates()
  {
    const rclcpp::Time t = this->now();
    for (auto & [topic, m] : mons_) {
      if (!m->pub) {
        continue;
      }
      const uint64_t c = m->count.load(std::memory_order_relaxed);
      m->samples.emplace_back(t, c);
      // Drop samples older than the window, but always keep at least two so a
      // span can be computed (and a stopped topic still decays to 0 as its last
      // arrivals age past the window edge).
      while (m->samples.size() > 2 &&
             (t - m->samples.front().first).seconds() > rate_window_s_) {
        m->samples.pop_front();
      }
      double hz = 0.0;
      if (m->samples.size() >= 2) {
        const double span = (t - m->samples.front().first).seconds();
        if (span > 0.0) {
          hz = static_cast<double>(c - m->samples.front().second) / span;
        }
      }
      std_msgs::msg::Float64 msg;
      msg.data = hz;
      m->pub->publish(msg);
    }
  }

  std::vector<std::string> topics_;
  double publish_period_;
  double rate_window_s_;
  rclcpp::QoS qos_{rclcpp::KeepLast(50)};
  std::map<std::string, std::shared_ptr<Mon>> mons_;
  rclcpp::TimerBase::SharedPtr discovery_timer_;
  rclcpp::TimerBase::SharedPtr publish_timer_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<TopicHzMonitor>());
  rclcpp::shutdown();
  return 0;
}
