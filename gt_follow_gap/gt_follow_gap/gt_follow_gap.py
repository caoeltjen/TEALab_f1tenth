#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from ackermann_msgs.msg import AckermannDriveStamped
import numpy as np
import concurrent.futures
import time

class ReactiveFollowGap(Node):
    """
    Implement Reactive Follow Gap on the car
    """

    def __init__(self):
        super().__init__('reactive_node')

        # Topics & Subs, Pubs
        self.lidarscan_topic = '/scan'
        self.drive_topic = '/drive'

        # Subscribe to LIDAR
        self.subscription = self.create_subscription(
            LaserScan,
            self.lidarscan_topic,
            self.lidar_callback,
            10
        )

        # Publish to drive
        self.publisher_ = self.create_publisher(
            AckermannDriveStamped,
            self.drive_topic,
            10
        )

        # Initialize the ReactiveFollowGap parameters
        self.radians_per_elem = None
        self.BUBBLE_RADIUS = 140
        self.PREPROCESS_CONV_SIZE = 3
        self.BEST_POINT_CONV_SIZE = 140
        self.MAX_LIDAR_DIST = 3.0
        self.STRAIGHTS_SPEED = 1.5
        self.CORNERS_SPEED = 0.5
        self.STRAIGHTS_STEERING_ANGLE = np.pi / 18 # 10 degrees
        self.MAX_STEERING_ANGLE = 40.0 * (np.pi / 180)

    def preprocess_lidar(self, ranges):
        """ Preprocess the LiDAR scan array."""
        self.radians_per_elem = (2 * np.pi) / len(ranges)
        # we won't use the LiDAR data from directly behind us
        proc_ranges = np.array(ranges[135:-135])
        # sets each value to the mean over a given window
        proc_ranges = np.convolve(proc_ranges, np.ones(self.PREPROCESS_CONV_SIZE), 'same') / self.PREPROCESS_CONV_SIZE
        proc_ranges = np.clip(proc_ranges, 0, self.MAX_LIDAR_DIST)
        return proc_ranges

    def find_max_gap(self, free_space_ranges):
        """ Return the start index & end index of the max gap in free_space_ranges"""
        # mask the bubble
        masked = np.ma.masked_where(free_space_ranges == 0, free_space_ranges)
        # get a slice for each contigous sequence of non-bubble data
        slices = np.ma.notmasked_contiguous(masked)
        max_len = slices[0].stop - slices[0].start
        chosen_slice = slices[0]
        # I think we will only ever have a maximum of 2 slices but will handle an
        # indefinitely sized list for portablility
        for sl in slices[1:]:
            sl_len = sl.stop - sl.start
            if sl_len > max_len:
                max_len = sl_len
                chosen_slice = sl
        return chosen_slice.start, chosen_slice.stop

    def find_best_point(self, start_i, end_i, ranges):
        """Start_i & end_i are start and end indices of max-gap range, respectively
        Return index of best point in ranges
        Naive: Choose the furthest point within ranges and go there
        """
        # do a sliding window average over the data in the max gap, this will
        # help the car to avoid hitting corners
        averaged_max_gap = np.convolve(ranges[start_i:end_i], np.ones(self.BEST_POINT_CONV_SIZE),
                                       'same') / self.BEST_POINT_CONV_SIZE
        print(averaged_max_gap)
        return averaged_max_gap.argmax() + start_i

    def get_angle(self, range_index, range_len):
        """ Get the angle of a particular element in the LiDAR data and transform it into an appropriate steering angle
        """
        lidar_angle = (range_index - (range_len / 2)) * self.radians_per_elem
        steering_angle = lidar_angle / 2
        return steering_angle

    def lidar_callback(self, data):
        """
        Process each LiDAR scan as per the Follow Gap algorithm
        and publish an AckermannDriveStamped Message
        """
        ranges = data.ranges
        proc_ranges = self.preprocess_lidar(ranges)

        # Find closest point to LiDAR
        closest = proc_ranges.argmin()

        # Eliminate all points inside 'bubble' (set them to zero)
        min_index = closest - self.BUBBLE_RADIUS
        max_index = closest + self.BUBBLE_RADIUS
        if min_index < 0: min_index = 0
        if max_index >= len(proc_ranges): max_index = len(proc_ranges) - 1
        proc_ranges[min_index:max_index] = 0

        # Find max length gap
        gap_start, gap_end = self.find_max_gap(proc_ranges)

        # Find the best point in the gap
        best = self.find_best_point(gap_start, gap_end, proc_ranges)

        # Publish Drive message
        steering_angle = self.get_angle(best, len(proc_ranges))
        
        if abs(steering_angle) > self.STRAIGHTS_STEERING_ANGLE:
            speed = self.CORNERS_SPEED
            if steering_angle > self.MAX_STEERING_ANGLE:
                steering_angle = -self.MAX_STEERING_ANGLE
            else:
                steering_angle = self.MAX_STEERING_ANGLE
        else:
            speed = self.STRAIGHTS_SPEED

        print('Steering angle in degrees: {}'.format((steering_angle / (np.pi / 2)) * 90))

        # Publish the drive message
        self.publish_drive(speed, steering_angle)

    def publish_drive(self, speed, steering_angle):
        """
        Publishes drive commands to the robot
        """
        drive_msg = AckermannDriveStamped()
        drive_msg.header.stamp = self.get_clock().now().to_msg()
        drive_msg.drive.steering_angle = steering_angle * 1.2
        drive_msg.drive.speed = speed
        self.publisher_.publish(drive_msg)


def main(args=None):
    rclpy.init(args=args)
    print("ReactiveFollowGap Initialized")
    reactive_node = ReactiveFollowGap()
    rclpy.spin(reactive_node)

    reactive_node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()