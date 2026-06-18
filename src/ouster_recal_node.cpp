/**
 * @file   ouster_recal_node.cpp
 * @brief  Estimate the Ouster internal-oscillator -> wall-clock offset from the
 *         100 Hz IMU, and expose it cheaply.
 *
 * Why: PTP won't lock on this rig (switch/HW issue), so the Ouster runs in
 * TIME_FROM_INTERNAL_OSC — a stable but free-running clock (≈ seconds since boot).
 * All Ouster outputs (points, images, IMU) share that one clock. The IMU is the
 * ideal calibration source: 100 Hz, tiny, never dropped, and (being tiny) the
 * lowest-latency, so the offset it gives is the closest estimate of the true
 * internal->wall mapping. One offset serves every Ouster topic.
 *
 * This node is deliberately MINIMAL — it does NOT republish the heavy point cloud
 * or images. It only:
 *   - publishes /ouster/imu_recal  (IMU restamped to wall-clock, for the EKF), and
 *   - publishes /ouster/clock_offset (std_msgs/Float64, seconds) so the buffer
 *     compositor adds it to the lidar stamps it already reads — no big-data hops.
 *
 * offset = EMA(now_wall - stamp_internal)   restamped = stamp_internal + offset.
 */
#include <cstdint>
#include <memory>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/imu.hpp"
#include "std_msgs/msg/float64.hpp"

class OusterRecalNode : public rclcpp::Node
{
public:
    OusterRecalNode() : rclcpp::Node("ouster_recal_node")
    {
        // EMA window in samples; at 100 Hz IMU, 100 ≈ 1 s. Smooths the ~12 ms
        // per-message latency jitter to ~1 ms while still tracking slow crystal drift.
        ema_n_ = this->declare_parameter<int>("ema_samples", 100);

        auto qos = rclcpp::SensorDataQoS();   // BEST_EFFORT, matches /ouster/imu

        imu_pub_    = this->create_publisher<sensor_msgs::msg::Imu>("/ouster/imu_recal", qos);
        offset_pub_ = this->create_publisher<std_msgs::msg::Float64>(
            "/ouster/clock_offset", rclcpp::QoS(rclcpp::KeepLast(1)).reliable().transient_local());
        imu_sub_ = this->create_subscription<sensor_msgs::msg::Imu>(
            "/ouster/imu", qos,
            std::bind(&OusterRecalNode::imuCb, this, std::placeholders::_1));

        // Publish the offset at 2 Hz (it changes slowly); TRANSIENT_LOCAL so a late
        // subscriber (the compositor) immediately gets the latest value.
        offset_timer_ = this->create_wall_timer(
            std::chrono::milliseconds(500), [this]() {
                if (!ready_) return;
                std_msgs::msg::Float64 m;
                m.data = static_cast<double>(offset_ns_) * 1e-9;
                offset_pub_->publish(m);
            });

        RCLCPP_INFO(get_logger(),
            "[ouster_recal] internal-osc -> wall-clock via /ouster/imu (EMA %d). "
            "Publishing /ouster/imu_recal + /ouster/clock_offset.", ema_n_);
    }

private:
    static int64_t toNs(const builtin_interfaces::msg::Time& t) {
        return static_cast<int64_t>(t.sec) * 1000000000LL + t.nanosec;
    }
    static builtin_interfaces::msg::Time fromNs(int64_t ns) {
        builtin_interfaces::msg::Time t;
        t.sec = static_cast<int32_t>(ns / 1000000000LL);
        t.nanosec = static_cast<uint32_t>(ns % 1000000000LL);
        return t;
    }

    void imuCb(sensor_msgs::msg::Imu::UniquePtr msg) {
        const int64_t stamp_ns = toNs(msg->header.stamp);
        const int64_t now_ns   = this->now().nanoseconds();
        const int64_t sample   = now_ns - stamp_ns;
        if (!ready_) {
            offset_ns_ = sample;
            ready_ = true;
        } else {
            // Integer EMA: offset += (sample - offset)/N. Full int64 precision
            // (offset is ~1.78e18 ns, too big for double without losing ms).
            offset_ns_ += (sample - offset_ns_) / ema_n_;
        }
        msg->header.stamp = fromNs(stamp_ns + offset_ns_);
        imu_pub_->publish(std::move(msg));
    }

    int     ema_n_;
    bool    ready_ = false;
    int64_t offset_ns_ = 0;

    rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr imu_sub_;
    rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr    imu_pub_;
    rclcpp::Publisher<std_msgs::msg::Float64>::SharedPtr   offset_pub_;
    rclcpp::TimerBase::SharedPtr offset_timer_;
};

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<OusterRecalNode>());
    rclcpp::shutdown();
    return 0;
}
